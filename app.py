from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from reportlab.lib.units import inch

from ai_service import (
    generate_smart_notes,
    generate_quiz,
    generate_flashcards,
)

from flask import Flask, render_template, request, jsonify
from pathlib import Path
import uuid
import subprocess
import whisper
import threading
import yt_dlp
import os

whisper_model = None


# =========================================================
# FLASK SETUP
# =========================================================

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"

UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024


# =========================================================
# WHISPER MODEL
# =========================================================


# =========================================================
# JOB STORAGE
# =========================================================

jobs = {}


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


# =========================================================
# WORKSPACE
# =========================================================

@app.route("/workspace")
def workspace():
    return render_template("workspace.html")


# =========================================================
# CREATE PROCESSING JOB
# =========================================================

def create_processing_job(video_id, original_name, saved_path):
    """
    Creates a job and starts the existing processing pipeline.
    Used by both normal uploads and YouTube downloads.
    """

    jobs[video_id] = {
        "status": "uploaded",
        "progress": 0,
        "message": "Video uploaded successfully.",
        "filename": original_name,
        "video_path": str(saved_path),
        "audio_path": None,
        "transcript": None,
        "notes": None,
        "quiz": None,
        "flashcards": None,
        "error": None
    }

    thread = threading.Thread(
        target=process_video,
        args=(video_id,)
    )

    thread.daemon = True
    thread.start()


# =========================================================
# UPLOAD VIDEO
# =========================================================

@app.route("/upload", methods=["POST"])
def upload_video():

    if "video" not in request.files:
        return jsonify({
            "success": False,
            "message": "No video file was selected."
        }), 400

    video = request.files["video"]

    if video.filename == "":
        return jsonify({
            "success": False,
            "message": "Please select a video."
        }), 400

    allowed_extensions = {
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm"
    }

    original_name = Path(video.filename).name
    extension = Path(original_name).suffix.lower()

    if extension not in allowed_extensions:
        return jsonify({
            "success": False,
            "message": "Unsupported video format."
        }), 400

    # Create unique ID
    video_id = str(uuid.uuid4())

    saved_filename = f"{video_id}{extension}"
    saved_path = UPLOAD_FOLDER / saved_filename

    try:

        video.save(saved_path)

        print()
        print("=" * 60)
        print("VIDEO UPLOAD SUCCESSFUL")
        print("Original:", original_name)
        print("Saved:", saved_path)
        print("Video ID:", video_id)
        print("=" * 60)

    except Exception as error:

        print("UPLOAD ERROR:", error)

        return jsonify({
            "success": False,
            "message": "The video could not be saved."
        }), 500

    create_processing_job(
        video_id,
        original_name,
        saved_path
    )

    return jsonify({
        "success": True,
        "message": "Video uploaded successfully.",
        "video_id": video_id,
        "filename": original_name
    })


# =========================================================
# YOUTUBE VIDEO
# =========================================================

@app.route("/youtube", methods=["POST"])
def youtube():
    data = request.get_json()

    if not data or not data.get("url"):
        return jsonify({
            "success": False,
            "error": "Please enter a YouTube URL."
        }), 400

    url = data["url"].strip()

    # Basic YouTube URL check
    if not (
        "youtube.com/watch" in url
        or "youtu.be/" in url
        or "youtube.com/shorts/" in url
    ):
        return jsonify({
            "success": False,
            "error": "Please enter a valid YouTube URL."
        }), 400

    video_id = str(uuid.uuid4())

    output_template = str(
        UPLOAD_FOLDER / f"{video_id}.%(ext)s"
    )

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "merge_output_format": "mp4"
    }

    try:
        print("\n==============================")
        print("YouTube download started")
        print("URL:", url)
        print("==============================\n")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        title = info.get("title", "YouTube Lecture")

        # Find the downloaded file
        downloaded_file = None

        for file in UPLOAD_FOLDER.glob(f"{video_id}.*"):
            if file.suffix.lower() in [
                ".mp4",
                ".webm",
                ".mkv",
                ".mov"
            ]:
                downloaded_file = file
                break

        if downloaded_file is None:
            raise Exception(
                "YouTube download completed, but the video file "
                "could not be found."
            )

        print("Downloaded:", downloaded_file)

        # Create processing job
        jobs[video_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Starting processing...",
            "filename": title,
            "video_path": str(downloaded_file),
            "audio_path": None,
            "transcript": "",
            "notes": "",
            "quiz": [],
            "flashcards": [],
            "error": None
        }

        # Start normal processing pipeline
        thread = threading.Thread(
            target=process_video,
            args=(video_id,),
            daemon=True
        )

        thread.start()

        return jsonify({
            "success": True,
            "video_id": video_id,
            "filename": title
        })

    except Exception as e:

        print("\n==============================")
        print("YOUTUBE ERROR")
        print(str(e))
        print("==============================\n")

        # Remove partially downloaded files
        for file in UPLOAD_FOLDER.glob(f"{video_id}.*"):
            try:
                file.unlink()
            except:
                pass

        return jsonify({
            "success": False,
            "error": "Could not download this YouTube video.",
            "details": str(e)
        }), 500

# =========================================================
# PROCESS VIDEO
# =========================================================

def process_video(video_id):

    global whisper_model

    job = jobs.get(video_id)

    if not job:
        return

    video_path = Path(job["video_path"])

    try:

        # =================================================
        # STEP 1 — AUDIO EXTRACTION
        # =================================================

        job["status"] = "processing"
        job["progress"] = 20
        job["message"] = "Extracting audio from lecture..."

        print()
        print("=" * 60)
        print("STEP 1: AUDIO EXTRACTION")
        print("=" * 60)

        audio_path = OUTPUT_FOLDER / f"{video_id}.wav"

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(audio_path)
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:

            print("FFMPEG ERROR:")
            print(result.stderr)

            raise RuntimeError(
                "Audio extraction failed."
            )

        job["audio_path"] = str(audio_path)

        print("Audio extracted successfully.")
        print(audio_path)

        # =================================================
        # STEP 2 — WHISPER TRANSCRIPTION
        # =================================================

        if whisper_model is None:

            print()
            print("Loading Whisper model...")

            whisper_model = whisper.load_model("tiny")

            print("Whisper model loaded successfully.")

        job["progress"] = 45
        job["message"] = "Transcribing lecture with Whisper..."

        print()
        print("=" * 60)
        print("STEP 2: WHISPER TRANSCRIPTION")
        print("=" * 60)

        result = whisper_model.transcribe(
            str(audio_path),
            fp16=False
        )

        transcript = result["text"].strip()

        if not transcript:

            raise RuntimeError(
                "Whisper could not detect any speech in the video."
            )

        job["transcript"] = transcript

        print("Transcription completed.")
        print("Characters:", len(transcript))

        # =================================================
        # STEP 3 — AI SMART NOTES
        # =================================================

        job["progress"] = 70
        job["message"] = "Generating smart notes with AI..."

        print()
        print("=" * 60)
        print("STEP 3: AI SMART NOTES")
        print("=" * 60)

        notes = generate_smart_notes(transcript)

        job["notes"] = notes

        print("Smart notes generated successfully.")

        # =================================================
        # STEP 4 — AI QUIZ
        # =================================================

        job["progress"] = 85
        job["message"] = "Creating quiz from your lecture..."

        print()
        print("=" * 60)
        print("STEP 4: AI QUIZ")
        print("=" * 60)

        quiz = generate_quiz(transcript)

        job["quiz"] = quiz

        print("Quiz generated successfully.")

        # =================================================
        # STEP 5 — AI FLASHCARDS
        # =================================================

        job["progress"] = 92
        job["message"] = "Creating flashcards from your lecture..."

        print()
        print("=" * 60)
        print("STEP 5: AI FLASHCARDS")
        print("=" * 60)

        flashcards = generate_flashcards(transcript)

        job["flashcards"] = flashcards

        print("Flashcards generated successfully.")

        # =================================================
        # COMPLETE
        # =================================================

        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Lecture processing completed."

        print()
        print("=" * 60)
        print("PROCESSING COMPLETE")
        print("=" * 60)

    except Exception as error:

        print()
        print("=" * 60)
        print("PROCESSING ERROR")
        print("=" * 60)
        print(error)
        print("=" * 60)

        job["status"] = "error"
        job["progress"] = 0
        job["message"] = str(error)
        job["error"] = str(error)

# =========================================================
# JOB STATUS
# =========================================================

@app.route("/status/<video_id>")
def job_status(video_id):

    job = jobs.get(video_id)

    if not job:

        return jsonify({
            "success": False,
            "message": "Processing job not found."
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
        "error": job["error"]
    })


# =========================================================
# TRANSCRIPT API
# =========================================================

@app.route("/transcript/<video_id>")
def get_transcript(video_id):

    job = jobs.get(video_id)

    if not job:

        return jsonify({
            "success": False,
            "message": "Video not found."
        }), 404

    if job["status"] != "completed":

        return jsonify({
            "success": False,
            "message": "Transcript is not ready yet."
        }), 400

    return jsonify({
        "success": True,
        "transcript": job["transcript"]
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
            "message": "Lecture not found."
        }), 404

    if job.get("status") != "completed":

        return jsonify({
            "success": False,
            "message": "Please wait until lecture processing is complete."
        }), 400

    pdf_path = OUTPUT_FOLDER / (
        f"DeepDive_Learning_Pack_{video_id}.pdf"
    )

    try:

        import html

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DeepDiveTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontSize=22,
            leading=28,
            spaceAfter=12
        )

        subtitle_style = ParagraphStyle(
            "DeepDiveSubtitle",
            parent=styles["Heading2"],
            alignment=TA_CENTER,
            fontSize=12,
            leading=16,
            spaceAfter=20
        )

        heading_style = ParagraphStyle(
            "DeepDiveHeading",
            parent=styles["Heading1"],
            fontSize=16,
            leading=20,
            spaceBefore=10,
            spaceAfter=10
        )

        normal_style = ParagraphStyle(
            "DeepDiveNormal",
            parent=styles["BodyText"],
            fontSize=10,
            leading=15,
            spaceAfter=7
        )

        def safe_text(value):

            if value is None:
                return ""

            return html.escape(
                str(value)
            ).replace(
                "\n",
                "<br/>"
            )

        def add_value(value):

            if value is None:
                return

            if isinstance(value, list):

                for item in value:

                    if isinstance(item, dict):

                        for key, val in item.items():

                            if isinstance(
                                val,
                                (list, dict)
                            ):

                                add_value(val)

                            else:

                                story.append(
                                    Paragraph(
                                        f"<b>{safe_text(key.replace('_', ' ').title())}:</b> "
                                        f"{safe_text(val)}",
                                        normal_style
                                    )
                                )

                    else:

                        story.append(
                            Paragraph(
                                f"• {safe_text(item)}",
                                normal_style
                            )
                        )

            elif isinstance(value, dict):

                for key, val in value.items():

                    if isinstance(
                        val,
                        (list, dict)
                    ):

                        story.append(
                            Paragraph(
                                f"<b>{safe_text(key.replace('_', ' ').title())}</b>",
                                normal_style
                            )
                        )

                        add_value(val)

                    else:

                        story.append(
                            Paragraph(
                                f"<b>{safe_text(key.replace('_', ' ').title())}:</b> "
                                f"{safe_text(val)}",
                                normal_style
                            )
                        )

            else:

                story.append(
                    Paragraph(
                        safe_text(value),
                        normal_style
                    )
                )

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=50,
            leftMargin=50,
            topMargin=50,
            bottomMargin=50
        )

        story = []

        # -----------------------------------------------------
        # COVER
        # -----------------------------------------------------

        story.append(
            Spacer(1, 50)
        )

        story.append(
            Paragraph(
                "DeepDive AI",
                title_style
            )
        )

        story.append(
            Paragraph(
                "AI-Powered Learning Pack",
                subtitle_style
            )
        )

        story.append(
            Paragraph(
                f"<b>Lecture:</b> "
                f"{safe_text(job.get('filename', 'Lecture'))}",
                normal_style
            )
        )

        story.append(
            Spacer(1, 25)
        )

        story.append(
            Paragraph(
                "Generated from your lecture using DeepDive AI.",
                normal_style
            )
        )

        # -----------------------------------------------------
        # SMART NOTES
        # -----------------------------------------------------

        story.append(PageBreak())

        story.append(
            Paragraph(
                "1. Smart Notes",
                heading_style
            )
        )

        notes = job.get("notes")

        if notes:

            add_value(notes)

        else:

            story.append(
                Paragraph(
                    "No smart notes available.",
                    normal_style
                )
            )

        # -----------------------------------------------------
        # QUIZ
        # -----------------------------------------------------

        story.append(PageBreak())

        story.append(
            Paragraph(
                "2. Quiz",
                heading_style
            )
        )

        quiz = job.get("quiz")

        if isinstance(quiz, list) and quiz:

            for i, question in enumerate(
                quiz,
                start=1
            ):

                if isinstance(question, dict):

                    q_text = (
                        question.get("question")
                        or question.get("Question")
                        or f"Question {i}"
                    )

                    story.append(
                        Paragraph(
                            f"<b>{i}. {safe_text(q_text)}</b>",
                            normal_style
                        )
                    )

                    options = (
                        question.get("options")
                        or []
                    )

                    if isinstance(
                        options,
                        list
                    ):

                        for option in options:

                            story.append(
                                Paragraph(
                                    f"• {safe_text(option)}",
                                    normal_style
                                )
                            )

                    correct = (
                        question.get("correct_answer")
                        or question.get("correctAnswer")
                        or question.get("answer")
                    )

                    if correct:

                        story.append(
                            Paragraph(
                                f"<b>Answer:</b> "
                                f"{safe_text(correct)}",
                                normal_style
                            )
                        )

                    explanation = question.get(
                        "explanation"
                    )

                    if explanation:

                        story.append(
                            Paragraph(
                                f"<b>Explanation:</b> "
                                f"{safe_text(explanation)}",
                                normal_style
                            )
                        )

                    story.append(
                        Spacer(1, 8)
                    )

                else:

                    story.append(
                        Paragraph(
                            f"<b>{i}. "
                            f"{safe_text(question)}</b>",
                            normal_style
                        )
                    )

        else:

            story.append(
                Paragraph(
                    "No quiz available.",
                    normal_style
                )
            )

        # -----------------------------------------------------
        # FLASHCARDS
        # -----------------------------------------------------

        story.append(PageBreak())

        story.append(
            Paragraph(
                "3. Flashcards",
                heading_style
            )
        )

        flashcards = job.get("flashcards")

        if isinstance(
            flashcards,
            list
        ) and flashcards:

            for i, card in enumerate(
                flashcards,
                start=1
            ):

                if isinstance(card, dict):

                    front = (
                        card.get("front")
                        or card.get("question")
                        or card.get("term")
                        or card.get("word")
                        or f"Card {i}"
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
                            f"<b>{i}. "
                            f"{safe_text(front)}</b>",
                            normal_style
                        )
                    )

                    if back:

                        story.append(
                            Paragraph(
                                f"<b>Answer:</b> "
                                f"{safe_text(back)}",
                                normal_style
                            )
                        )

                    story.append(
                        Spacer(1, 8)
                    )

                else:

                    story.append(
                        Paragraph(
                            f"<b>{i}.</b> "
                            f"{safe_text(card)}",
                            normal_style
                        )
                    )

        else:

            story.append(
                Paragraph(
                    "No flashcards available.",
                    normal_style
                )
            )

        # -----------------------------------------------------
        # TRANSCRIPT
        # -----------------------------------------------------

        story.append(PageBreak())

        story.append(
            Paragraph(
                "4. Lecture Transcript",
                heading_style
            )
        )

        transcript = job.get(
            "transcript"
        )

        if transcript:

            add_value(transcript)

        else:

            story.append(
                Paragraph(
                    "No transcript available.",
                    normal_style
                )
            )

        doc.build(story)

        return jsonify({
            "success": True,
            "download_url": (
                f"/download-pdf/{video_id}"
            )
        })

    except Exception as error:

        print(
            "PDF GENERATION ERROR:",
            error
        )

        return jsonify({
            "success": False,
            "message": "Could not generate the PDF.",
            "error": str(error)
        }), 500


# =========================================================
# DOWNLOAD PDF
# =========================================================

@app.route("/download-pdf/<video_id>")
def download_pdf(video_id):

    pdf_path = OUTPUT_FOLDER / (
        f"DeepDive_Learning_Pack_{video_id}.pdf"
    )

    if not pdf_path.exists():

        return jsonify({
            "success": False,
            "message": "PDF has not been generated yet."
        }), 404

    from flask import send_file

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name="DeepDive_Learning_Pack.pdf",
        mimetype="application/pdf"
    )


# =========================================================
# FILE TOO LARGE
# =========================================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "success": False,
        "message": "Video is too large. Maximum size is 500 MB."
    }), 413


# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        debug=True,
        host="0.0.0.0",
        port=port
    )