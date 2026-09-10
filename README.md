# DeepDive AI – AI-Powered Learning Assistant

DeepDive AI is an AI-powered learning assistant that transforms lecture videos and YouTube lectures into organized study material. It uses speech-to-text transcription and generative AI to create Smart Notes, quizzes, flashcards, transcripts, and a downloadable Learning Pack.

The project is designed to make lecture revision faster, more organized, and easier for students.

## Features

### 🎥 Lecture Video Upload

Upload a lecture video directly to the application.

Supported formats include:

* MP4
* MOV
* AVI
* MKV
* WEBM

### ▶️ YouTube Lecture Processing

Paste a public YouTube lecture URL and DeepDive AI downloads and processes the lecture automatically.

### 📝 AI Transcription

The lecture audio is extracted using FFmpeg and converted into text using AssemblyAI's speech-to-text API.

### 📚 Smart Notes

Gemini AI analyzes the lecture transcript and generates structured study notes covering the important concepts.

### 🧠 AI Quiz

DeepDive AI generates a multiple-choice quiz from the lecture content to help students test their understanding.

### 🗂️ Flashcards

Important concepts are converted into question-and-answer flashcards for quick revision.

### 📄 Transcript

The complete lecture transcript can be viewed inside the learning workspace.

### 📘 Learning Pack

Students can generate a downloadable PDF containing:

* Smart Notes
* Quiz
* Flashcards
* Lecture Transcript

## How DeepDive AI Works

The application follows a simple processing pipeline:

```text
Lecture Video / YouTube URL
          ↓
      Flask Backend
          ↓
    FFmpeg Audio Extraction
          ↓
    AssemblyAI Transcription
          ↓
       Lecture Text
          ↓
        Gemini AI
     ↙      ↓      ↘
  Notes    Quiz   Flashcards
     \       |       /
      \      |      /
       Learning Pack
            ↓
          PDF
```

## Technology Stack

### Frontend

* HTML5
* CSS3
* JavaScript

The frontend provides the landing page, upload interface, processing screen, and learning workspace.

### Backend

* Python
* Flask

Flask handles:

* File uploads
* YouTube processing
* Background processing
* Job status tracking
* API routes
* Transcript delivery
* PDF generation

### AI & APIs

#### AssemblyAI

AssemblyAI is used for speech-to-text transcription.

The lecture audio is sent to AssemblyAI and the resulting transcript is returned to the Flask backend.

#### Google Gemini

Gemini is used to generate:

* Smart Notes
* Quiz questions
* Flashcards

### Media Processing

**FFmpeg** is used to extract audio from uploaded lecture videos and prepare it for transcription.

### YouTube Processing

**yt-dlp** is used to retrieve publicly accessible YouTube lecture videos.

### PDF Generation

**ReportLab** is used to generate the downloadable Learning Pack PDF.

### Deployment

The application is containerized using:

* Docker
* Gunicorn
* Render

## Project Architecture

```text
DeepDive-AI-Learning-Assistant-Flask/
│
├── app.py
├── requirements.txt
├── Dockerfile
├── .gitignore
│
├── templates/
│   ├── index.html
│   └── workspace.html
│
├── static/
│   ├── css/
│   │   └── style.css
│   │
│   └── js/
│       └── app.js
│
├── services/
│   ├── ai_service.py
│   └── ...
│
├── uploads/
│   └── .gitkeep
│
└── outputs/
    └── .gitkeep
```

> The exact contents of the `services` directory may vary as the project is developed.

## Application Workflow

### 1. Select a Lecture

The user can either:

* Upload a lecture video
* Provide a YouTube lecture URL

### 2. Audio Extraction

For uploaded videos, FFmpeg extracts the audio from the lecture and converts it into a suitable audio format.

### 3. Transcription

The extracted audio is sent to AssemblyAI.

AssemblyAI converts the spoken lecture into text.

### 4. AI Processing

The transcript is provided to Gemini AI for educational content generation.

DeepDive AI creates:

* Smart Notes
* Quiz
* Flashcards

### 5. Learning Workspace

The generated content is displayed in the DeepDive AI workspace.

The user can review the transcript, notes, quiz, and flashcards.

### 6. Learning Pack

The user can generate a PDF containing the complete study material.

## Installation

### Prerequisites

Make sure the following are installed:

* Python 3.11 or compatible Python version
* Git
* FFmpeg
* A Google Gemini API key
* An AssemblyAI API key

## Clone the Repository

```bash
git clone https://github.com/samrudhibandbuche-ui/DeepDive-AI-Learning-Assistant-Flask.git
```

Move into the project directory:

```bash
cd DeepDive-AI-Learning-Assistant-Flask
```

## Create a Virtual Environment

Windows:

```bash
python -m venv venv
```

Activate it:

```bash
venv\Scripts\activate
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

The main dependencies include:

```text
Flask
yt-dlp
reportlab
google-genai
python-dotenv
gunicorn
assemblyai
```

## Environment Variables

Create a `.env` file in the project root.

```env
GEMINI_API_KEY=your_gemini_api_key
ASSEMBLYAI_API_KEY=your_assemblyai_api_key
```

Replace the values with your own API keys.

### Important

Do not upload your `.env` file to GitHub.

The project includes `.env` in `.gitignore` to help prevent API keys from being committed accidentally.

## Run the Application Locally

Start the Flask application:

```bash
python app.py
```

The application will normally be available at:

```text
http://127.0.0.1:5000
```

Open the address in a web browser.

## Docker

The project includes a Dockerfile for deployment.

The Docker image installs FFmpeg and the Python dependencies required by the application.

Build the Docker image:

```bash
docker build -t deepdive-ai .
```

Run the container:

```bash
docker run -p 5000:5000 deepdive-ai
```

For production deployment, Gunicorn is used to serve the Flask application.

## Deployment

DeepDive AI is designed to run as a Docker-based Flask application on Render.

The deployment architecture is:

```text
GitHub Repository
       ↓
      Render
       ↓
 Docker Container
       ↓
 Gunicorn
       ↓
 Flask Application
       ↓
AssemblyAI + Gemini
```

### Required Render Environment Variables

Add the following environment variables to the Render service:

```text
GEMINI_API_KEY
ASSEMBLYAI_API_KEY
```

The API keys should be stored as environment variables rather than directly inside the source code.

## Security

DeepDive AI uses environment variables for API credentials.

Sensitive files and generated data are excluded from Git using `.gitignore`.

The following should not be committed to the repository:

* API keys
* `.env`
* Uploaded lecture videos
* Generated PDF files
* Virtual environment files
* Temporary files

## Error Handling

The application includes handling for common situations such as:

* Unsupported video formats
* Missing processing jobs
* Failed transcription
* Empty transcripts
* Missing API keys
* YouTube download failures
* Oversized uploads
* PDF generation errors

The application also maintains processing status so that the frontend can display the current stage of lecture processing.

## Why AssemblyAI Instead of Local Whisper?

The initial version of DeepDive AI used Whisper for local transcription.

While local Whisper provides speech-to-text functionality, it requires additional machine-learning dependencies such as PyTorch and can require significant computational resources during cloud deployment.

For the deployed version, AssemblyAI was used as a cloud-based speech-to-text service.

This makes the deployment lighter and avoids requiring the Render server to load a local Whisper model.

## Why Gemini?

Gemini provides generative AI capabilities that are useful for converting raw lecture transcripts into structured learning material.

DeepDive AI uses Gemini to generate:

* Structured Smart Notes
* Multiple-choice quizzes
* Revision flashcards

This allows the application to go beyond simple transcription and provide educational content derived from the lecture.

## Why Flask?

Flask was selected as the backend framework because it is lightweight, flexible, and suitable for building the web API and processing workflow required by DeepDive AI.

Flask connects the frontend with:

* Video processing
* Transcription
* AI generation
* PDF generation
* Job status tracking

## Advantages

* Converts lectures into structured study material
* Supports both video uploads and YouTube lectures
* Reduces manual note-taking
* Provides multiple revision formats
* Combines transcription and generative AI
* Provides a downloadable Learning Pack
* Can be deployed as a web application

## Limitations

The current version has some practical limitations:

* Processing time depends on lecture length.
* Cloud AI services are subject to API usage limits and availability.
* YouTube processing depends on the availability and accessibility of the provided video.
* Uploaded and generated files are stored temporarily by the application.
* Very large lecture videos may require more processing resources.

## Future Scope

Possible future improvements include:

* User accounts and personalized learning history
* Persistent cloud storage
* Progress tracking
* More advanced quiz types
* Difficulty-based quizzes
* Better multilingual transcription
* Support for additional learning resources
* Improved search within transcripts
* Voice-based learning features
* Personalized revision recommendations
* Scalable background processing

## Project Objective

The main objective of DeepDive AI is to create a single learning workspace that can transform lengthy lecture content into useful study resources.

Instead of manually watching a lecture, taking notes, creating questions, and preparing revision material separately, the application combines these tasks into one AI-assisted workflow.

## Conclusion

DeepDive AI demonstrates how modern web development, speech-to-text technology, generative AI, and media processing can be combined to create a practical educational application.

The project provides an end-to-end workflow:

```text
Lecture
   ↓
Transcription
   ↓
AI Analysis
   ↓
Notes + Quiz + Flashcards
   ↓
Learning Workspace
   ↓
Learning Pack
```

## Project

**DeepDive AI – AI-Powered Learning Assistant**

Built using Python, Flask, JavaScript, FFmpeg, AssemblyAI, Gemini AI, ReportLab, Docker, and Render.

---

## License

This project is developed as an academic/project demonstration. Add an appropriate open-source license if you decide to distribute the project publicly.
