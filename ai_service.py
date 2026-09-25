import os
import json
import re
import time
import random

from dotenv import load_dotenv
from google import genai


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing from the .env file."
    )

client = genai.Client(api_key=API_KEY)

# Keep the stable model you are already using.
MODEL_NAME = "gemini-3.6-flash"

# Extra protection for temporary Gemini 429/503/5xx errors.
MAX_RETRIES = 4
INITIAL_RETRY_DELAY = 2


# ============================================================
# GEMINI ERROR HELPERS
# ============================================================

class GeminiTemporaryUnavailable(RuntimeError):
    """Raised when Gemini remains temporarily unavailable after retries."""


def _is_retryable_error(error_text):
    text = error_text.lower()

    return (
        "503" in text
        or "unavailable" in text
        or "service_unavailable" in text
        or "429" in text
        or "resource_exhausted" in text
        or "rate limit" in text
        or "temporarily" in text
        or "500" in text
        or "internal" in text
        or "504" in text
        or "deadline exceeded" in text
    )


def _is_daily_quota_error(error_text):
    text = error_text.lower()

    return (
        "perday" in text
        or "daily quota" in text
        or "quota exceeded" in text and "retrydelay" not in text.lower()
    )


# ============================================================
# GEMINI REQUEST HELPER
# ============================================================

def _generate_content(prompt, config=None):
    """
    Sends a request to Gemini.

    Temporary 429/503/500/504 errors are retried with
    exponential backoff and jitter.

    If Gemini is still temporarily unavailable after all
    retries, a special error is raised so the caller can
    switch to the local fallback instead of crashing the
    entire DeepDive processing job.
    """

    last_error = None

    for attempt in range(MAX_RETRIES):

        try:

            if config is not None:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=config
                )
            else:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt
                )

            if not response or not response.text:
                raise RuntimeError(
                    "The AI returned an empty response."
                )

            return response.text.strip()

        except Exception as error:

            last_error = error
            error_text = str(error)

            print()
            print("=" * 60)
            print("GEMINI REQUEST ERROR")
            print("=" * 60)
            print(error_text)
            print("=" * 60)

            # Daily quota is not fixed by retrying.
            if _is_daily_quota_error(error_text):
                print("GEMINI DAILY QUOTA EXHAUSTED")
                raise RuntimeError(
                    "GEMINI_DAILY_QUOTA_EXHAUSTED"
                )

            # Only retry temporary/server-side failures.
            if not _is_retryable_error(error_text):
                raise

            if attempt < MAX_RETRIES - 1:

                # 2s, 4s, 8s with a small random jitter.
                wait_time = INITIAL_RETRY_DELAY * (2 ** attempt)
                wait_time += random.uniform(0, 1)

                print(
                    f"Temporary Gemini error. "
                    f"Retrying in {wait_time:.1f} seconds "
                    f"(attempt {attempt + 2}/{MAX_RETRIES})..."
                )

                time.sleep(wait_time)

    # Important:
    # Do NOT let a final 503 escape as a fatal application error.
    print()
    print("=" * 60)
    print("GEMINI STILL UNAVAILABLE AFTER RETRIES")
    print("SWITCHING TO LOCAL FALLBACK MODE")
    print("=" * 60)

    raise GeminiTemporaryUnavailable(
        str(last_error)
        if last_error
        else "Gemini is temporarily unavailable."
    )


# ============================================================
# SMART NOTES
# ============================================================

def generate_smart_notes(transcript):

    if not transcript or not transcript.strip():
        raise ValueError("Transcript is empty.")

    prompt = f"""
You are DeepDive AI, an AI learning assistant.

Create clear and useful study notes from the lecture
transcript below.

IMPORTANT RULES:

- Use ONLY the lecture transcript.
- Do not add outside information.
- Do not invent facts.
- Organize the material clearly.
- Use headings and bullet points.
- Explain important concepts in simple language.
- Keep important definitions, examples and explanations.
- Make the notes useful for a college student preparing
  for exams.
- Do not mention these instructions.

LECTURE TRANSCRIPT:

{transcript}

Create the study notes now.
"""

    try:
        notes = _generate_content(prompt)
        return notes.strip()

    except RuntimeError as error:

        if str(error) == "GEMINI_DAILY_QUOTA_EXHAUSTED":
            return generate_fallback_notes(transcript)

        raise

    except GeminiTemporaryUnavailable as error:
        print("Smart Notes: Gemini temporarily unavailable.")
        print("Smart Notes: Using local fallback.")
        return generate_fallback_notes(transcript)


# ============================================================
# QUIZ GENERATOR
# ============================================================

def generate_quiz(transcript):

    if not transcript or not transcript.strip():
        raise ValueError("Transcript is empty.")

    prompt = f"""
You are DeepDive AI.

Create exactly 10 multiple-choice questions from the
lecture transcript below.

IMPORTANT:

- Use ONLY information from the transcript.
- Do not use outside knowledge.
- Do not invent facts.
- Each question must have exactly 4 options.
- Only one option must be correct.
- Include a short explanation.
- Return ONLY valid JSON.
- Do not use Markdown.
- Do not wrap the JSON in ```.

Required JSON format:

[
  {{
    "question": "Question text",
    "options": [
      "Option A",
      "Option B",
      "Option C",
      "Option D"
    ],
    "correct_answer": "Correct option",
    "explanation": "Short explanation"
  }}
]

LECTURE TRANSCRIPT:

{transcript}
"""

    try:

        quiz_text = _generate_content(
            prompt,
            config={
                "response_mime_type": "application/json"
            }
        )

        quiz_text = quiz_text.strip()

        # Remove accidental markdown fences.
        if quiz_text.startswith("```json"):
            quiz_text = quiz_text[7:]

        if quiz_text.startswith("```"):
            quiz_text = quiz_text[3:]

        if quiz_text.endswith("```"):
            quiz_text = quiz_text[:-3]

        quiz_text = quiz_text.strip()

        # Find JSON array if Gemini added extra text.
        start = quiz_text.find("[")
        end = quiz_text.rfind("]")

        if start == -1 or end == -1:
            raise ValueError(
                "AI returned invalid quiz format."
            )

        quiz_text = quiz_text[start:end + 1]
        quiz = json.loads(quiz_text)

        # Validate.
        if not isinstance(quiz, list):
            raise ValueError(
                "Quiz response is not a list."
            )

        if len(quiz) != 10:
            raise ValueError(
                f"Expected 10 questions, got {len(quiz)}."
            )

        for question in quiz:

            required_fields = [
                "question",
                "options",
                "correct_answer",
                "explanation"
            ]

            for field in required_fields:

                if field not in question:
                    raise ValueError(
                        f"Quiz question missing field: {field}"
                    )

            if len(question["options"]) != 4:
                raise ValueError(
                    "Each quiz question must have exactly "
                    "4 options."
                )

            if question["correct_answer"] not in question["options"]:
                raise ValueError(
                    "Correct answer must be one of the options."
                )

        print()
        print("=" * 60)
        print("QUIZ GENERATED SUCCESSFULLY")
        print("=" * 60)

        return quiz

    except RuntimeError as error:

        if str(error) == "GEMINI_DAILY_QUOTA_EXHAUSTED":
            print("Using fallback quiz.")
            return generate_fallback_quiz(transcript)

        raise

    except GeminiTemporaryUnavailable:
        print("Quiz: Gemini temporarily unavailable.")
        print("Quiz: Using local fallback.")
        return generate_fallback_quiz(transcript)


# ============================================================
# FLASHCARD GENERATOR
# ============================================================

def generate_flashcards(transcript):

    if not transcript or not transcript.strip():
        raise ValueError("Transcript is empty.")

    prompt = f"""
You are DeepDive AI.

Create exactly 10 study flashcards from the lecture
transcript below.

IMPORTANT:

- Use ONLY information from the transcript.
- Do not use outside knowledge.
- Do not invent facts.
- Each flashcard must contain:
  question
  answer
- Keep answers concise and useful for revision.
- Return ONLY valid JSON.
- Do not use Markdown.
- Do not wrap the JSON in ```.

Required format:

[
  {{
    "question": "Question",
    "answer": "Answer"
  }}
]

LECTURE TRANSCRIPT:

{transcript}
"""

    try:

        flashcards_text = _generate_content(
            prompt,
            config={
                "response_mime_type": "application/json"
            }
        )

        flashcards_text = flashcards_text.strip()

        if flashcards_text.startswith("```json"):
            flashcards_text = flashcards_text[7:]

        if flashcards_text.startswith("```"):
            flashcards_text = flashcards_text[3:]

        if flashcards_text.endswith("```"):
            flashcards_text = flashcards_text[:-3]

        flashcards_text = flashcards_text.strip()

        start = flashcards_text.find("[")
        end = flashcards_text.rfind("]")

        if start == -1 or end == -1:
            raise ValueError(
                "AI returned invalid flashcard format."
            )

        flashcards_text = flashcards_text[start:end + 1]
        flashcards = json.loads(flashcards_text)

        if not isinstance(flashcards, list):
            raise ValueError(
                "Flashcards response is not a list."
            )

        if len(flashcards) != 10:
            raise ValueError(
                f"Expected 10 flashcards, got {len(flashcards)}."
            )

        for card in flashcards:

            if "question" not in card:
                raise ValueError(
                    "Flashcard is missing question."
                )

            if "answer" not in card:
                raise ValueError(
                    "Flashcard is missing answer."
                )

            if not str(card["question"]).strip():
                raise ValueError(
                    "Flashcard question is empty."
                )

            if not str(card["answer"]).strip():
                raise ValueError(
                    "Flashcard answer is empty."
                )

        print()
        print("=" * 60)
        print("FLASHCARDS GENERATED SUCCESSFULLY")
        print("=" * 60)

        return flashcards

    except RuntimeError as error:

        if str(error) == "GEMINI_DAILY_QUOTA_EXHAUSTED":
            print("Using fallback flashcards.")
            return generate_fallback_flashcards(transcript)

        raise

    except GeminiTemporaryUnavailable:
        print("Flashcards: Gemini temporarily unavailable.")
        print("Flashcards: Using local fallback.")
        return generate_fallback_flashcards(transcript)


# ============================================================
# LOCAL FALLBACK HELPERS
# ============================================================

def _clean_text(text):
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(transcript):

    transcript = _clean_text(transcript)

    if not transcript:
        return []

    sentences = re.split(
        r"(?<=[.!?])\s+",
        transcript
    )

    return [
        sentence.strip()
        for sentence in sentences
        if len(sentence.strip()) > 20
    ]


# ============================================================
# FALLBACK NOTES
# ============================================================

def generate_fallback_notes(transcript):

    sentences = _split_sentences(transcript)

    if not sentences:
        return (
            "### Lecture Notes\n\n"
            "Gemini is temporarily unavailable. "
            "The lecture transcript is available, but "
            "there is not enough structured text to create "
            "detailed notes."
        )

    selected = sentences[:25]

    notes = [
        "### Lecture Notes",
        "",
        "Fallback mode: Gemini was temporarily unavailable.",
        "The following key points were extracted directly "
        "from the lecture transcript.",
        "",
        "### Key Lecture Points",
        ""
    ]

    for sentence in selected:
        notes.append(f"- {sentence}")

    return "\n".join(notes)


# ============================================================
# FALLBACK QUIZ
# ============================================================

def generate_fallback_quiz(transcript):

    sentences = _split_sentences(transcript)
    quiz = []

    for index in range(10):

        if sentences:
            sentence = sentences[index % len(sentences)]
            correct_answer = sentence
        else:
            correct_answer = (
                "Information from the lecture transcript."
            )

        quiz.append({
            "question": (
                "Which statement is directly supported "
                f"by the lecture? (Question {index + 1})"
            ),
            "options": [
                correct_answer,
                "This information was not discussed.",
                "This is unrelated to the lecture.",
                "None of these statements."
            ],
            "correct_answer": correct_answer,
            "explanation": (
                "The correct option is taken directly from "
                "the lecture transcript."
            )
        })

    return quiz


# ============================================================
# FALLBACK FLASHCARDS
# ============================================================

def generate_fallback_flashcards(transcript):

    sentences = _split_sentences(transcript)
    flashcards = []

    for index in range(10):

        if sentences:
            sentence = sentences[index % len(sentences)]
        else:
            sentence = (
                "The lecture transcript does not contain "
                "enough text for this flashcard."
            )

        flashcards.append({
            "question": (
                f"What does the lecture state in point "
                f"{index + 1}?"
            ),
            "answer": sentence
        })

    return flashcards
