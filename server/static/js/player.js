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

function loadVideoAtTime(globalTime) {
    let accumulated = 0;
    for (let i = 0; i < videoList.length; i++) {
        let vid = videoList[i];
        if (globalTime < accumulated + vid.duration_seconds) {
            currentVideoIndex = i;
            let localTime = globalTime - accumulated;
            player.src = `/video/${vid.filename}`;
            player.currentTime = localTime;
            player.play();
            currentGlobalTime = globalTime;
            return;
        }
        accumulated += vid.duration_seconds;
    }

    console.log("Reached end of all videos");
}

function seek(seconds) {
    let newTime = currentGlobalTime + seconds;
    if (newTime < 0) newTime = 0;
    currentGlobalTime = newTime;
    loadVideoAtTime(newTime);
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

loadPlaylist();