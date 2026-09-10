import os
import json
import re
import time

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

MODEL_NAME = "gemini-3.6-flash"

# Number of automatic retries for temporary API errors
MAX_RETRIES = 3


# ============================================================
# GEMINI REQUEST HELPER
# ============================================================

def _generate_content(prompt, config=None):
    """
    Sends a request to Gemini.

    Handles temporary 429/503 errors using exponential backoff.

    Returns:
        response.text

    Raises:
        Exception if the request permanently fails.
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

            # ------------------------------------------------
            # Check whether this looks like a quota/rate error
            # ------------------------------------------------

            is_retryable = (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
                or "rate limit" in error_text.lower()
                or "temporarily" in error_text.lower()
            )

            if not is_retryable:
                raise

            # ------------------------------------------------
            # If this is a daily quota exhaustion, retrying
            # repeatedly is not useful.
            # ------------------------------------------------

            daily_quota = (
                "PerDay" in error_text
                or "perday" in error_text.lower()
                or "daily quota" in error_text.lower()
                or "quota exceeded" in error_text.lower()
                and "retryDelay" not in error_text
            )

            if daily_quota:

                print()
                print("GEMINI DAILY QUOTA EXHAUSTED")
                print("Using local fallback mode.")
                print()

                raise RuntimeError(
                    "GEMINI_DAILY_QUOTA_EXHAUSTED"
                )

            # ------------------------------------------------
            # Exponential backoff
            # ------------------------------------------------

            if attempt < MAX_RETRIES - 1:

                wait_time = 2 ** attempt

                print(
                    f"Retrying Gemini request in "
                    f"{wait_time} seconds..."
                )

                time.sleep(wait_time)

    raise last_error


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

        # Remove accidental markdown fences
        if quiz_text.startswith("```json"):
            quiz_text = quiz_text[7:]

        if quiz_text.startswith("```"):
            quiz_text = quiz_text[3:]

        if quiz_text.endswith("```"):
            quiz_text = quiz_text[:-3]

        quiz_text = quiz_text.strip()

        # Find JSON array if Gemini added extra text
        start = quiz_text.find("[")
        end = quiz_text.rfind("]")

        if start == -1 or end == -1:
            raise ValueError(
                "AI returned invalid quiz format."
            )

        quiz_text = quiz_text[start:end + 1]

        quiz = json.loads(quiz_text)

        # Validate
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

            if not card["question"].strip():
                raise ValueError(
                    "Flashcard question is empty."
                )

            if not card["answer"].strip():
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

            return generate_fallback_flashcards(
                transcript
            )

        raise



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
            "The lecture transcript is available, but "
            "there is not enough structured text to create "
            "detailed notes."
        )

    selected = sentences[:25]

    notes = [
        "### Lecture Notes",
        "",
        "⚠️ **Offline fallback mode**",
        "",
        "Gemini is temporarily unavailable because the "
        "API quota has been exhausted. The following "
        "notes are extracted directly from the lecture "
        "transcript.",
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

    # We need 10 questions for the existing frontend.
    for index in range(10):

        if sentences:

            sentence = sentences[
                index % len(sentences)
            ]

            # Keep sentence as correct answer.
            correct_answer = sentence

        else:

            correct_answer = (
                "Information from the lecture transcript."
            )

        quiz.append({
            "question": (
                f"Which statement is taken from the "
                f"lecture content? (Question {index + 1})"
            ),
            "options": [
                correct_answer,
                "This information was not discussed.",
                "This is unrelated to the lecture.",
                "None of these statements."
            ],
            "correct_answer": correct_answer,
            "explanation": (
                "This option was extracted directly from "
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

            sentence = sentences[
                index % len(sentences)
            ]

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


