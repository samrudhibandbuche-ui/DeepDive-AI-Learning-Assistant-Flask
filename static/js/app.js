// ==================================================
// DEEPDIVE AI 2.0
// FRONTEND JAVASCRIPT
// ==================================================


let selectedVideo = null;


// ==================================================
// MODAL
// ==================================================

function openWorkspace() {

    const modal = document.getElementById("workspaceModal");

    if (modal) {
        modal.classList.add("active");
        document.body.classList.add("modal-open");
    }
}


function closeWorkspace() {

    const modal = document.getElementById("workspaceModal");

    if (modal) {
        modal.classList.remove("active");
        document.body.classList.remove("modal-open");
    }
}


// Close modal when clicking outside it

const modal = document.getElementById("workspaceModal");

if (modal) {

    modal.addEventListener("click", function(event) {

        if (event.target === modal) {
            closeWorkspace();
        }

    });

}


// ==================================================
// VIDEO INPUT
// ==================================================

const videoInput = document.getElementById("videoInput");

if (videoInput) {

    videoInput.addEventListener("change", function() {

        if (this.files.length > 0) {

            handleVideo(this.files[0]);

        }

    });

}


// ==================================================
// DRAG AND DROP
// ==================================================

const uploadBox = document.getElementById("uploadBox");

if (uploadBox) {

    uploadBox.addEventListener("dragover", function(event) {

        event.preventDefault();

        uploadBox.classList.add("dragging");

    });


    uploadBox.addEventListener("dragleave", function() {

        uploadBox.classList.remove("dragging");

    });


    uploadBox.addEventListener("drop", function(event) {

        event.preventDefault();

        uploadBox.classList.remove("dragging");

        const files = event.dataTransfer.files;

        if (files.length > 0) {

            handleVideo(files[0]);

        }

    });

}


// ==================================================
// HANDLE VIDEO
// ==================================================

function handleVideo(file) {

    clearUploadError();


    const allowedExtensions = [
        "mp4",
        "mov",
        "avi",
        "mkv",
        "webm"
    ];


    const filename = file.name.toLowerCase();

    const extension = filename
        .split(".")
        .pop();


    if (!allowedExtensions.includes(extension)) {

        showUploadError(
            "Please choose a supported video format."
        );

        return;

    }


    // 500 MB limit

    const maxSize =
        500 * 1024 * 1024;


    if (file.size > maxSize) {

        showUploadError(
            "This video is larger than 500 MB."
        );

        return;

    }


    selectedVideo = file;


    displaySelectedFile(file);

}


// ==================================================
// DISPLAY SELECTED FILE
// ==================================================

function displaySelectedFile(file) {

    const selectedFile =
        document.getElementById("selectedFile");

    const fileName =
        document.getElementById("fileName");

    const fileSize =
        document.getElementById("fileSize");

    const startButton =
        document.getElementById("startSessionButton");


    if (!selectedFile) {
        return;
    }


    fileName.textContent = file.name;


    const sizeMB =
        (file.size / (1024 * 1024)).toFixed(1);


    fileSize.textContent =
        `${sizeMB} MB`;


    selectedFile.classList.add("visible");


    if (startButton) {

        startButton.disabled = false;

    }

}


// ==================================================
// REMOVE VIDEO
// ==================================================

function removeSelectedFile() {

    selectedVideo = null;


    const selectedFile =
        document.getElementById("selectedFile");

    const videoInput =
        document.getElementById("videoInput");

    const startButton =
        document.getElementById("startSessionButton");


    if (selectedFile) {

        selectedFile.classList.remove("visible");

    }


    if (videoInput) {

        videoInput.value = "";

    }


    if (startButton) {

        startButton.disabled = true;

    }


    clearUploadError();

}


// ==================================================
// UPLOAD VIDEO
// ==================================================

async function uploadVideo() {

    if (!selectedVideo) {
        showUploadError("Please select a video first.");
        return;
    }

    clearUploadError();

    const button = document.getElementById("startSessionButton");

    button.disabled = true;

    button.innerHTML = `
        Processing...
    `;

    const formData = new FormData();

    formData.append("video", selectedVideo);

    try {

        const response = await fetch("/upload", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (!response.ok || !data.success) {

            throw new Error(
                data.message || "Upload failed."
            );
        }

        sessionStorage.setItem(
            "deepdive_video_id",
            data.video_id
        );

        sessionStorage.setItem(
            "deepdive_video_name",
            data.filename
        );

        // Go to workspace
        window.location.href =
            "/workspace";

    } catch (error) {

        console.error(error);

        showUploadError(
            error.message ||
            "Something went wrong while uploading the video."
        );

        button.disabled = false;

        button.innerHTML = `
            Start Learning →
        `;
    }
}

// ==================================================
// ERROR DISPLAY
// ==================================================

function showUploadError(message) {

    const errorBox =
        document.getElementById("uploadError");


    if (!errorBox) {
        return;
    }


    errorBox.textContent =
        message;


    errorBox.classList.add("visible");

}


function clearUploadError() {

    const errorBox =
        document.getElementById("uploadError");


    if (!errorBox) {
        return;
    }


    errorBox.textContent = "";

    errorBox.classList.remove("visible");

}


// ==================================================
// LOAD WORKSPACE VIDEO NAME
// ==================================================

document.addEventListener(
    "DOMContentLoaded",
    function() {

        const videoName =
            sessionStorage.getItem(
                "deepdive_video_name"
            );


        const workspaceHeading =
            document.querySelector(
                ".workspace-heading h1"
            );


        if (
            videoName &&
            workspaceHeading
        ) {

            workspaceHeading.textContent =
                videoName;

        }

    }
);