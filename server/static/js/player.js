let videoList = [];
let currentGlobalTime = 0;
let currentVideoIndex = 0;
let player = document.getElementById("player");
let timestampDisplay = document.getElementById("timestamp");

async function loadPlaylist() {
    const response = await fetch("/playlist");
    videoList = await response.json();

    if (videoList.length === 0) {
        alert("No videos found.");
        return;
    }

    loadVideoAtTime(0);
    setInterval(updateTimestamp, 100);  // live update
}

function getSeekStep() {
    const input = document.getElementById("seekStep");
    const val = parseFloat(input.value);
    return isNaN(val) || val <= 0 ? 0.5 : val;
}

function loadVideoAtTime(globalTime, preservePause = false) {
    let accumulated = 0;
    for (let i = 0; i < videoList.length; i++) {
        let vid = videoList[i];
        if (globalTime < accumulated + vid.duration_seconds) {
            currentVideoIndex = i;
            let localTime = globalTime - accumulated;
            player.src = `/video/${vid.filename}`;
            player.onloadedmetadata = () => {
                player.currentTime = localTime;
                if (!preservePause) player.play(); // only autoplay if not preserving pause
            };
            currentGlobalTime = globalTime;
            return;
        }
        accumulated += vid.duration_seconds;
    }

    console.log("Reached end of all videos");
}

function seek(seconds) {
    const wasPaused = player.paused;

    let newTime = currentGlobalTime + seconds;
    if (newTime < 0) newTime = 0;
    currentGlobalTime = newTime;

    loadVideoAtTime(newTime, wasPaused);
}

function updateTimestamp() {
    let vid = videoList[currentVideoIndex];
    if (!vid) return;

    let videoStart = new Date(vid.start);
    let displayTime = new Date(videoStart.getTime() + player.currentTime * 1000);
    timestampDisplay.textContent = "Timestamp: " + displayTime.toLocaleString();

    currentGlobalTime = computeGlobalTime();
}

function computeGlobalTime() {
    let time = 0;
    for (let i = 0; i < currentVideoIndex; i++) {
        time += videoList[i].duration_seconds;
    }
    return time + player.currentTime;
}

player.addEventListener("ended", () => {
    const nextIndex = currentVideoIndex + 1;
    if (nextIndex < videoList.length) {
        currentVideoIndex = nextIndex;
        loadVideoAtTime(computeGlobalTime()); // continue playback
    }
});

document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") seek(-getSeekStep());
    if (e.key === "ArrowRight") seek(getSeekStep());
});

document.addEventListener('keydown', function(event) {
    if (event.key === "Enter") {
        const seekInput = document.getElementById("seekStep");
        if (document.activeElement === seekInput) {
            // If already focused, blur it (exit)
            seekInput.blur();
        } else {
            // Else, focus the input box
            seekInput.focus();
        }
        event.preventDefault();  // prevent form submit or default enter behavior
    }
});

loadPlaylist();
