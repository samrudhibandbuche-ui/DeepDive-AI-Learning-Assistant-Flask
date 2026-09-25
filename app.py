from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from ai_service import (
    generate_smart_notes,
    generate_quiz,
    generate_flashcards,
)

from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi

import uuid
import subprocess
import threading
import os
import assemblyai as aai

print("🔥🔥🔥 NEW DEEPDIVE AI_SERVICE.PY LOADED 🔥🔥🔥")
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT AND FLASK SETUP
# =========================================================

load_dotenv()
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"

UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024


# =========================================================
# IN-MEMORY JOB STORAGE
# =========================================================

jobs = {}


# =========================================================
# PAGE ROUTES
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/workspace")
def workspace():
    return render_template("workspace.html")


# =========================================================
# COMMON JOB HELPERS
# =========================================================

def create_job(video_id, filename, video_path=None):
    jobs[video_id] = {
        "status": "uploaded",
        "progress": 0,
        "message": "Video uploaded successfully.",
        "filename": filename,
        "video_path": str(video_path) if video_path else None,
        "audio_path": None,
        "transcript": None,
        "notes": None,
        "quiz": None,
        "flashcards": None,
        "error": None,
    }


def start_background_job(target, video_id, *args):
    thread = threading.Thread(
        target=target,
        args=(video_id, *args),
        daemon=True,
    )
    thread.start()


# =========================================================
# LOCAL VIDEO UPLOAD
# =========================================================

@app.route("/upload", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({
            "success": False,
            "message": "No video file was selected.",
        }), 400

    video = request.files["video"]

    if not video.filename:
        return jsonify({
            "success": False,
            "message": "Please select a video.",
        }), 400

    allowed_extensions = {
        ".mp4", ".mov", ".avi", ".mkv", ".webm"
    }

    original_name = Path(video.filename).name
    extension = Path(original_name).suffix.lower()

    if extension not in allowed_extensions:
        return jsonify({
            "success": False,
            "message": "Unsupported video format.",
        }), 400

    video_id = str(uuid.uuid4())
    saved_path = UPLOAD_FOLDER / f"{video_id}{extension}"

    try:
        video.save(saved_path)
        create_job(video_id, original_name, saved_path)
        start_background_job(process_video, video_id)

        print("LOCAL VIDEO UPLOAD SUCCESSFUL:", saved_path)

        return jsonify({
            "success": True,
            "message": "Video uploaded successfully.",
            "video_id": video_id,
            "filename": original_name,
        })

    except Exception as error:
        print("UPLOAD ERROR:", error)
        return jsonify({
            "success": False,
            "message": "The video could not be saved.",
            "error": str(error),
        }), 500


# =========================================================
# YOUTUBE URL HELPERS
# =========================================================

def extract_youtube_video_id(url):
    """Extract a YouTube video ID from common YouTube URLs."""

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]

        if path.startswith("/shorts/"):
            return path.split("/shorts/", 1)[1].split("/", 1)[0]

        if path.startswith("/embed/"):
            return path.split("/embed/", 1)[1].split("/", 1)[0]

    if hostname in {"youtu.be", "www.youtu.be"}:
        return path.strip("/").split("/", 1)[0] or None

    return None


def transcript_snippet_text(snippet):
    """Support both object-style and dictionary-style snippets."""

    if hasattr(snippet, "text"):
        return str(snippet.text)

    if isinstance(snippet, dict):
        return str(snippet.get("text", ""))

    return str(snippet)



def fetch_youtube_transcript(youtube_video_id):
    """
    Fetch an available English or Hindi YouTube transcript
    without downloading the video.
    """

    try:

        api = YouTubeTranscriptApi()

        fetched = api.fetch(
            youtube_video_id,
            languages=["en", "hi"],
        )

        parts = [
            transcript_snippet_text(snippet)
            for snippet in fetched
        ]

        transcript = " ".join(parts).strip()

        if not transcript:

            raise RuntimeError(
                "The video has no readable English or Hindi transcript."
            )

        return transcript

    except Exception as error:

        error_text = str(error).lower()

        print("=" * 60)
        print("YOUTUBE TRANSCRIPT FETCH FAILED")
        print("Video ID:", youtube_video_id)
        print("Error:", str(error))
        print("=" * 60)

        if (
            "ip" in error_text
            or "blocked" in error_text
            or "sign in" in error_text
            or "requestblocked" in error_text
        ):

            raise RuntimeError(
                "YouTube blocked the transcript request from "
                "the Render server. Please try a local video "
                "upload or provide the lecture transcript."
            ) from error

        if (
            "disabled" in error_text
            or "no transcript" in error_text
            or "not found" in error_text
        ):

            raise RuntimeError(
                "This YouTube video does not have an accessible transcript."
            ) from error

        raise RuntimeError(
            f"Could not retrieve the YouTube transcript: {error}"
        ) from error


# =========================================================
# YOUTUBE TRANSCRIPT PROCESSING
# =========================================================

@app.route("/youtube", methods=["POST"])
def youtube():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()

    if not url:
        return jsonify({
            "success": False,
            "error": "Please enter a YouTube URL.",
        }), 400

    youtube_id = extract_youtube_video_id(url)

    if not youtube_id:
        return jsonify({
            "success": False,
            "error": "Please enter a valid YouTube URL.",
        }), 400

    job_id = str(uuid.uuid4())

    create_job(
        job_id,
        "YouTube Lecture",
        video_path=None,
    )

    jobs[job_id]["status"] = "processing"
    jobs[job_id]["message"] = "Starting YouTube transcript extraction..."

    start_background_job(
        process_youtube_transcript,
        job_id,
        youtube_id,
    )

    print("YOUTUBE TRANSCRIPT JOB STARTED:", youtube_id)

    return jsonify({
        "success": True,
        "video_id": job_id,
        "filename": "YouTube Lecture",
    })


def process_youtube_transcript(video_id, youtube_id):
    job = jobs.get(video_id)

    if not job:
        return

    try:
        job["status"] = "processing"
        job["progress"] = 20
        job["message"] = "Fetching YouTube transcript..."

        print("=" * 60)
        print("YOUTUBE TRANSCRIPT EXTRACTION")
        print("Video ID:", youtube_id)
        print("=" * 60)

        transcript = fetch_youtube_transcript(youtube_id)
        job["transcript"] = transcript

        print("Transcript extracted successfully.")
        print("Characters:", len(transcript))

        job["progress"] = 60
        job["message"] = "Generating smart notes with AI..."
        job["notes"] = generate_smart_notes(transcript)

        job["progress"] = 78
        job["message"] = "Creating quiz from your lecture..."
        job["quiz"] = generate_quiz(transcript)

        job["progress"] = 92
        job["message"] = "Creating flashcards from your lecture..."
        job["flashcards"] = generate_flashcards(transcript)

        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "YouTube learning pack generated successfully."

        print("YOUTUBE PROCESSING COMPLETE")

    except Exception as error:
        print("YOUTUBE TRANSCRIPT ERROR:", error)
        job["status"] = "error"
        job["progress"] = 0
        job["message"] = "Could not extract the YouTube transcript."
        job["error"] = str(error)

        # =========================================================
# MANUAL TRANSCRIPT PROCESSING
# =========================================================

@app.route("/transcript-text", methods=["POST"])
def transcript_text():

    data = request.get_json(silent=True) or {}

    transcript = str(
        data.get("transcript", "")
    ).strip()

    if not transcript:

        return jsonify({
            "success": False,
            "error": "Please paste a transcript first."
        }), 400

    if len(transcript) < 30:

        return jsonify({
            "success": False,
            "error": "The transcript is too short. Please paste more content."
        }), 400

    video_id = str(uuid.uuid4())

    jobs[video_id] = {
        "status": "processing",
        "progress": 10,
        "message": "Starting transcript processing...",
        "filename": "Pasted Transcript",
        "video_path": None,
        "audio_path": None,
        "transcript": transcript,
        "notes": None,
        "quiz": None,
        "flashcards": None,
        "error": None
    }

    thread = threading.Thread(
        target=process_transcript_text,
        args=(video_id,),
        daemon=True
    )

    thread.start()

    return jsonify({
        "success": True,
        "video_id": video_id,
        "filename": "Pasted Transcript"
    })


def process_transcript_text(video_id):

    job = jobs.get(video_id)

    if not job:
        return

    try:

        transcript = job["transcript"]

        job["status"] = "processing"
        job["progress"] = 30
        job["message"] = "Generating smart notes with AI..."

        job["notes"] = generate_smart_notes(transcript)

        job["progress"] = 60
        job["message"] = "Creating quiz from your transcript..."

        job["quiz"] = generate_quiz(transcript)

        job["progress"] = 85
        job["message"] = "Creating flashcards from your transcript..."

        job["flashcards"] = generate_flashcards(transcript)

        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Learning pack generated successfully."

        print("MANUAL TRANSCRIPT PROCESSING COMPLETE")

    except Exception as error:

        print("MANUAL TRANSCRIPT ERROR:", error)

        job["status"] = "error"
        job["progress"] = 0
        job["message"] = str(error)
        job["error"] = str(error)


# =========================================================
# LOCAL VIDEO PROCESSING
# =========================================================

def process_video(video_id):
    job = jobs.get(video_id)

    if not job or not job.get("video_path"):
        return

    video_path = Path(job["video_path"])

    try:
        # STEP 1: AUDIO EXTRACTION
        job["status"] = "processing"
        job["progress"] = 20
        job["message"] = "Extracting audio from lecture..."

        audio_path = OUTPUT_FOLDER / f"{video_id}.wav"

        command = [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(audio_path),
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            print("FFMPEG ERROR:", result.stderr)
            raise RuntimeError("Audio extraction failed.")

        job["audio_path"] = str(audio_path)

        # STEP 2: ASSEMBLYAI TRANSCRIPTION
        job["progress"] = 45
        job["message"] = "Transcribing lecture with AI..."

        if not os.getenv("ASSEMBLYAI_API_KEY"):
            raise RuntimeError("AssemblyAI API key is not configured.")

        transcriber = aai.Transcriber()
        transcript_result = transcriber.transcribe(str(audio_path))

        if transcript_result.status == aai.TranscriptStatus.error:
            raise RuntimeError(
                f"Transcription failed: {transcript_result.error}"
            )

        transcript = (transcript_result.text or "").strip()

        if not transcript:
            raise RuntimeError("No speech was detected in the lecture.")

        job["transcript"] = transcript

        # STEP 3: SMART NOTES
        job["progress"] = 70
        job["message"] = "Generating smart notes with AI..."
        job["notes"] = generate_smart_notes(transcript)

        # STEP 4: QUIZ
        job["progress"] = 85
        job["message"] = "Creating quiz from your lecture..."
        job["quiz"] = generate_quiz(transcript)

        # STEP 5: FLASHCARDS
        job["progress"] = 92
        job["message"] = "Creating flashcards from your lecture..."
        job["flashcards"] = generate_flashcards(transcript)

        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Lecture processing completed."

        print("LOCAL VIDEO PROCESSING COMPLETE")

    except Exception as error:
        print("PROCESSING ERROR:", error)
        job["status"] = "error"
        job["progress"] = 0
        job["message"] = str(error)
        job["error"] = str(error)


# =========================================================
# JOB STATUS AND TRANSCRIPT API
# =========================================================

@app.route("/status/<video_id>")
def job_status(video_id):
    job = jobs.get(video_id)

    if not job:
        return jsonify({
            "success": False,
            "message": "Processing job not found.",
        }), 404

    return jsonify({
        "success": True,
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "filename": job["filename"],
        "transcript": job["transcript"],
        "notes": job["notes"],
        "quiz": job["quiz"],
        "flashcards": job["flashcards"],
        "error": job["error"],
    })


@app.route("/transcript/<video_id>")
def get_transcript(video_id):
    job = jobs.get(video_id)

    if not job:
        return jsonify({
            "success": False,
            "message": "Video not found.",
        }), 404

    if job["status"] != "completed":
        return jsonify({
            "success": False,
            "message": "Transcript is not ready yet.",
        }), 400

    return jsonify({
        "success": True,
        "transcript": job["transcript"],
    })


# =========================================================
# PDF LEARNING PACK
# =========================================================

@app.route("/pdf/<video_id>")
def generate_pdf(video_id):
    job = jobs.get(video_id)

    if not job:
        return jsonify({
            "success": False,
            "message": "Lecture not found.",
        }), 404

    if job.get("status") != "completed":
        return jsonify({
            "success": False,
            "message": "Please wait until lecture processing is complete.",
        }), 400

    pdf_path = OUTPUT_FOLDER / f"DeepDive_Learning_Pack_{video_id}.pdf"

    try:
        import html

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DeepDiveTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontSize=22,
            leading=28,
            spaceAfter=12,
        )

        subtitle_style = ParagraphStyle(
            "DeepDiveSubtitle",
            parent=styles["Heading2"],
            alignment=TA_CENTER,
            fontSize=12,
            leading=16,
            spaceAfter=20,
        )

        heading_style = ParagraphStyle(
            "DeepDiveHeading",
            parent=styles["Heading1"],
            fontSize=16,
            leading=20,
            spaceBefore=10,
            spaceAfter=10,
        )

        normal_style = ParagraphStyle(
            "DeepDiveNormal",
            parent=styles["BodyText"],
            fontSize=10,
            leading=15,
            spaceAfter=7,
        )

        def safe_text(value):
            if value is None:
                return ""
            return html.escape(str(value)).replace("\n", "<br/>")

        story = []

        def add_value(value):
            if value is None:
                return

            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for key, val in item.items():
                            if isinstance(val, (list, dict)):
                                story.append(
                                    Paragraph(
                                        f"<b>{safe_text(key.replace('_', ' ').title())}</b>",
                                        normal_style,
                                    )
                                )
                                add_value(val)
                            else:
                                story.append(
                                    Paragraph(
                                        f"<b>{safe_text(key.replace('_', ' ').title())}:</b> {safe_text(val)}",
                                        normal_style,
                                    )
                                )
                    else:
                        story.append(
                            Paragraph(f"• {safe_text(item)}", normal_style)
                        )

            elif isinstance(value, dict):
                for key, val in value.items():
                    if isinstance(val, (list, dict)):
                        story.append(
                            Paragraph(
                                f"<b>{safe_text(key.replace('_', ' ').title())}</b>",
                                normal_style,
                            )
                        )
                        add_value(val)
                    else:
                        story.append(
                            Paragraph(
                                f"<b>{safe_text(key.replace('_', ' ').title())}:</b> {safe_text(val)}",
                                normal_style,
                            )
                        )

            else:
                story.append(Paragraph(safe_text(value), normal_style))

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=50,
            leftMargin=50,
            topMargin=50,
            bottomMargin=50,
        )

        # COVER
        story.append(Spacer(1, 50))
        story.append(Paragraph("DeepDive AI", title_style))
        story.append(Paragraph("AI-Powered Learning Pack", subtitle_style))
        story.append(
            Paragraph(
                f"<b>Lecture:</b> {safe_text(job.get('filename', 'Lecture'))}",
                normal_style,
            )
        )
        story.append(Spacer(1, 25))
        story.append(
            Paragraph(
                "Generated from your lecture using DeepDive AI.",
                normal_style,
            )
        )

        # SMART NOTES
        story.append(PageBreak())
        story.append(Paragraph("1. Smart Notes", heading_style))
        if job.get("notes"):
            add_value(job["notes"])
        else:
            story.append(Paragraph("No smart notes available.", normal_style))

        # QUIZ
        story.append(PageBreak())
        story.append(Paragraph("2. Quiz", heading_style))
        quiz = job.get("quiz")

        if isinstance(quiz, list) and quiz:
            for index, question in enumerate(quiz, start=1):
                if isinstance(question, dict):
                    question_text = (
                        question.get("question")
                        or question.get("Question")
                        or f"Question {index}"
                    )
                    story.append(
                        Paragraph(
                            f"<b>{index}. {safe_text(question_text)}</b>",
                            normal_style,
                        )
                    )

                    options = question.get("options") or []
                    if isinstance(options, list):
                        for option in options:
                            story.append(
                                Paragraph(f"• {safe_text(option)}", normal_style)
                            )

                    answer = (
                        question.get("correct_answer")
                        or question.get("correctAnswer")
                        or question.get("answer")
                    )
                    if answer:
                        story.append(
                            Paragraph(
                                f"<b>Answer:</b> {safe_text(answer)}",
                                normal_style,
                            )
                        )

                    explanation = question.get("explanation")
                    if explanation:
                        story.append(
                            Paragraph(
                                f"<b>Explanation:</b> {safe_text(explanation)}",
                                normal_style,
                            )
                        )

                    story.append(Spacer(1, 8))
                else:
                    story.append(
                        Paragraph(
                            f"<b>{index}. {safe_text(question)}</b>",
                            normal_style,
                        )
                    )
        else:
            story.append(Paragraph("No quiz available.", normal_style))

        # FLASHCARDS
        story.append(PageBreak())
        story.append(Paragraph("3. Flashcards", heading_style))
        flashcards = job.get("flashcards")

        if isinstance(flashcards, list) and flashcards:
            for index, card in enumerate(flashcards, start=1):
                if isinstance(card, dict):
                    front = (
                        card.get("front")
                        or card.get("question")
                        or card.get("term")
                        or card.get("word")
                        or f"Card {index}"
                    )
                    back = (
                        card.get("back")
                        or card.get("answer")
                        or card.get("definition")
                        or card.get("explanation")
                        or ""
                    )

                    story.append(
                        Paragraph(
                            f"<b>{index}. {safe_text(front)}</b>",
                            normal_style,
                        )
                    )
                    if back:
                        story.append(
                            Paragraph(
                                f"<b>Answer:</b> {safe_text(back)}",
                                normal_style,
                            )
                        )
                    story.append(Spacer(1, 8))
                else:
                    story.append(
                        Paragraph(
                            f"<b>{index}.</b> {safe_text(card)}",
                            normal_style,
                        )
                    )
        else:
            story.append(Paragraph("No flashcards available.", normal_style))

        # TRANSCRIPT
        story.append(PageBreak())
        story.append(Paragraph("4. Lecture Transcript", heading_style))
        if job.get("transcript"):
            add_value(job["transcript"])
        else:
            story.append(Paragraph("No transcript available.", normal_style))

        doc.build(story)

        return jsonify({
            "success": True,
            "download_url": f"/download-pdf/{video_id}",
        })

    except Exception as error:
        print("PDF GENERATION ERROR:", error)
        return jsonify({
            "success": False,
            "message": "Could not generate the PDF.",
            "error": str(error),
        }), 500


# =========================================================
# DOWNLOAD PDF
# =========================================================

@app.route("/download-pdf/<video_id>")
def download_pdf(video_id):
    pdf_path = OUTPUT_FOLDER / f"DeepDive_Learning_Pack_{video_id}.pdf"

    if not pdf_path.exists():
        return jsonify({
            "success": False,
            "message": "PDF has not been generated yet.",
        }), 404

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name="DeepDive_Learning_Pack.pdf",
        mimetype="application/pdf",
    )


# =========================================================
# FILE TOO LARGE HANDLER
# =========================================================

@app.errorhandler(413)
def file_too_large(error):
    return jsonify({
        "success": False,
        "message": "Video is too large. Maximum size is 500 MB.",
    }), 413


# =========================================================
# RUN SERVER
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        debug=True,
        host="0.0.0.0",
        port=port,
    )
