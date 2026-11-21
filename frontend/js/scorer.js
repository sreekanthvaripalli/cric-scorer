/**
 * Cric-Scorer — Scorer Controller
 * Offline-first scoring UI with IndexedDB queue
 */

(function () {
  "use strict";

  const API_BASE = window.location.origin;
  let matchId = null;
  let matchData = null;
  let offlineQueue = [];
  let isConnected = true;

  // Scoring state
  let currentOver = 1;
  let currentBall = 1;
  let strikerId = 1;
  let nonStrikerId = 2;
  let bowlerId = 3;

  const matchName = document.getElementById("match-name");
  const matchStatus = document.getElementById("match-status");
  const teamA = document.getElementById("team-a");
  const teamB = document.getElementById("team-b");
  const scoreDisplay = document.getElementById("score-display");
  const ballCount = document.getElementById("ball-count");
  const oversDisplay = document.getElementById("overs");
  const buttonsContainer = document.getElementById("buttons");
  const btn0 = document.getElementById("btn-0");
  const btn1 = document.getElementById("btn-1");
  const btn2 = document.getElementById("btn-2");
  const btn3 = document.getElementById("btn-3");
  const btn4 = document.getElementById("btn-4");
  const btn5 = document.getElementById("btn-5");
  const btn6 = document.getElementById("btn-6");
  const btnNb = document.getElementById("btn-nb");
  const btnWd = document.getElementById("btn-wd");
  const btnBye = document.getElementById("btn-bye");
  const btnWk = document.getElementById("btn-wk");
  const btnUndo = document.getElementById("btn-undo");
  const btnOverComplete = document.getElementById("btn-over-complete");
  const statusLog = document.getElementById("status-log");
  const offlineBadge = document.getElementById("offline-badge");

  const numberButtons = [
    { id: btn0, value: 0 }, { id: btn1, value: 1 },
    { id: btn2, value: 2 }, { id: btn3, value: 3 },
    { id: btn4, value: 4 }, { id: btn5, value: 5 },
    { id: btn6, value: 6 }, { id: btnNb, value: "nb" },
    { id: btnWd, value: "wd" }, { id: btnBye, value: "bye" },
    { id: btnWk, value: "wicket" }
  ];

  numberButtons.forEach((btn) => {
    if (btn.id) {
      btn.id.addEventListener("click", () => recordDelivery(btn.value));
    }
  });

  if (btnUndo) btnUndo.addEventListener("click", undoLastBall);
  if (btnOverComplete) btnOverComplete.addEventListener("click", completeOver);

  async function fetchData() {
    try {
      const response = await fetch(API_BASE + "/matches/" + matchId + "/public");
      if (!response.ok) throw new Error("Failed: " + response.status);
      matchData = await response.json();
      updateMatchInfo();
      loadOfflineQueue();
    } catch (error) {
      console.error("Error:", error);
      showStatus("Error: " + error.message, "error");
    }
  }

  function updateMatchInfo() {
    if (matchName) matchName.textContent = matchData.name || "";
    if (matchStatus) matchStatus.textContent = matchData.status || "";
    if (teamA) teamA.textContent = matchData.team_a_name || "";
    if (teamB) teamB.textContent = matchData.team_b_name || "";
    if (scoreDisplay) scoreDisplay.textContent = (matchData.team_a_name || "") + " vs " + (matchData.team_b_name || "");
  }

  async function recordDelivery(value) {
    if (!matchId) return;
    const isWicket = value === "wicket";
    const isNb = value === "nb";
    const isWd = value === "wd";
    const isBye = value === "bye";

    const delivery = {
      match_id: matchId,
      bowler_id: bowlerId,
      striker_id: strikerId,
      non_striker_id: nonStrikerId,
      over_number: currentOver,
      ball_number: currentBall,
      runs_batter: isWicket ? 0 : (typeof value === "number" ? value : 0),
      runs_extras: 0,
      extra_type: isNb ? "nb" : isWd ? "wd" : isBye ? "bye" : null,
      penalty_runs: 0,
      is_wicket: isWicket,
      dismissal_mode: isWicket ? "caught" : null,
      fielder_id: isWicket ? bowlerId : null,
      short_runs: 0,
      boundary_type: typeof value === "number" && (value === 4 || value === 6) ? String(value) : null,
      is_free_hit: false,
      is_valid_ball: !isNb && !isWd,
      delivery_type: value,
      queued_at: new Date().toISOString(),
    };
    offlineQueue.push(delivery);
    await saveToIndexedDB(delivery);
    updateOfflineBadge();
    if (isConnected) {
      await sendDelivery(delivery);
      offlineQueue = offlineQueue.filter(d => d.id !== delivery.id);
      updateOfflineBadge();
      // Advance ball state
      currentBall++;
      if (currentBall > 6) {
        currentBall = 1;
        currentOver++;
      }
      // Rotate strike on odd runs
      if (typeof value === "number" && value % 2 === 1) {
        [strikerId, nonStrikerId] = [nonStrikerId, strikerId];
      }
    }
  }

  async function sendDelivery(delivery) {
    try {
      const response = await fetch(API_BASE + "/matches/" + matchId + "/balls", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bowler_id: delivery.bowler_id,
          striker_id: delivery.striker_id,
          non_striker_id: delivery.non_striker_id,
          over_number: delivery.over_number,
          ball_number: delivery.ball_number,
          runs_batter: delivery.runs_batter,
          runs_extras: delivery.runs_extras,
          extra_type: delivery.extra_type,
          penalty_runs: delivery.penalty_runs,
          is_wicket: delivery.is_wicket,
          dismissal_mode: delivery.dismissal_mode,
          fielder_id: delivery.fielder_id,
          short_runs: delivery.short_runs,
          boundary_type: delivery.boundary_type,
          is_free_hit: delivery.is_free_hit,
          is_valid_ball: delivery.is_valid_ball,
          delivery_type: delivery.delivery_type,
        }),
      });
      if (!response.ok) throw new Error("Server error: " + response.status);
      showStatus("Delivery recorded", "success");
    } catch (error) {
      showStatus("Failed: " + error.message, "error");
    }
  }

  async function saveToIndexedDB(delivery) {
    const db = await openDatabase();
    if (!db) return false;
    const id = Date.now() + Math.random();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("deliveries", "readwrite");
      const store = tx.objectStore("deliveries");
      const request = store.put({ ...delivery, id });
      request.onsuccess = () => resolve(true);
      request.onerror = () => reject(request.error);
    });
  }

  function loadOfflineQueue() {
    asyncOpenDatabase().then((db) => {
      if (!db) return;
      const tx = db.transaction("deliveries", "readonly");
      const store = tx.objectStore("deliveries");
      const request = store.getAll();
      request.onsuccess = () => {
        const deliveries = request.result;
        deliveries.forEach(d => offlineQueue.push(d));
        if (isConnected) syncOfflineQueue();
      };
    });
  }

  async function syncOfflineQueue() {
    const db = await openDatabase();
    if (!db) return;
    const tx = db.transaction("deliveries", "readwrite");
    const store = tx.objectStore("deliveries");
    const request = store.getAll();
    request.onsuccess = async () => {
      const deliveries = request.result;
      for (const delivery of deliveries) {
        try {
          await sendDelivery(delivery);
          await asyncDelete("deliveries", delivery.id);
        } catch (e) { console.error("Sync failed:", e); }
      }
      updateOfflineBadge();
    };
  }

  async function undoLastBall() {
    if (!matchId) return;
    try {
      const response = await fetch(API_BASE + "/matches/" + matchId + "/undo");
      if (!response.ok) throw new Error("Failed");
      showStatus("Last ball undone", "success");
    } catch (error) {
      showStatus("Failed: " + error.message, "error");
    }
  }

  async function completeOver() {
    if (!matchId) return;
    try {
      const response = await fetch(API_BASE + "/matches/" + matchId + "/balls/over-complete");
      if (!response.ok) throw new Error("Failed");
      showStatus("Over complete", "success");
    } catch (error) {
      showStatus("Failed: " + error.message, "error");
    }
  }

  function updateOfflineBadge() {
    if (offlineBadge) {
      offlineBadge.textContent = offlineQueue.length;
      offlineBadge.style.display = offlineQueue.length > 0 ? "block" : "none";
    }
  }

  function showStatus(message, type) {
    const log = document.getElementById("status-log");
    const entry = document.createElement("div");
    entry.className = "status-item status-item--" + (type || "info");
    entry.textContent = "[" + new Date().toLocaleTimeString() + "] " + message;
    log.insertBefore(entry, log.firstChild);
    while (log.children.length > 10) log.removeChild(log.lastChild);
  }

  function openDatabase() {
    return new Promise((resolve) => {
      const request = indexedDB.open("cric-scoring", 1);
      request.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("deliveries")) {
          const store = db.createObjectStore("deliveries", { keyPath: "id", autoIncrement: true });
          store.createIndex("match_id", "match_id", { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
    });
  }

  function asyncOpenDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("cric-scoring", 1);
      request.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("deliveries")) {
          const store = db.createObjectStore("deliveries", { keyPath: "id", autoIncrement: true });
          store.createIndex("match_id", "match_id", { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function asyncPut(storeName, data) {
    return new Promise((resolve, reject) => {
      openDatabase().then((db) => {
        if (!db) return resolve(false);
        const tx = db.transaction(storeName, "readwrite");
        const store = tx.objectStore(storeName);
        const req = store.put(data);
        req.onsuccess = () => resolve(true);
        req.onerror = () => reject(req.error);
      });
    });
  }

  function asyncDelete(storeName, id) {
    return new Promise((resolve, reject) => {
      openDatabase().then((db) => {
        if (!db) return resolve(false);
        const tx = db.transaction(storeName, "readwrite");
        const store = tx.objectStore(storeName);
        const req = store.delete(id);
        req.onsuccess = () => resolve(true);
        req.onerror = () => reject(req.error);
      });
    });
  }

  async function fetchMVP() {
    try {
      const response = await fetch(API_BASE + "/matches/" + matchId + "/mvp");
      if (!response.ok) return;
      const data = await response.json();
      if (data.mvp) {
        displayMVP(data.mvp);
      }
    } catch (e) {
      console.error("MVP fetch failed:", e);
    }
  }

  function displayMVP(mvp) {
    const section = document.getElementById("mvp-section");
    const content = document.getElementById("mvp-content");
    if (!section || !content) return;

    section.classList.remove("hidden");

    let html = "";
    html += "<p><strong>MVP:</strong> " + mvp.player_name + "</p>";
    html += "<p><strong>Points:</strong> " + mvp.points + "</p>";
    if (mvp.reason_summary) {
      html += "<p><strong>Reason:</strong> " + mvp.reason_summary + "</p>";
    }
    html += "<p><strong>Awarded:</strong> " + (mvp.awarded_at || "—") + "</p>";
    content.innerHTML = html;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const params = new URLSearchParams(window.location.search);
    matchId = params.get("match_id") || window.location.pathname.split("/").pop();
    if (!matchId) {
      showStatus("Match ID not found", "error");
      return;
    }
    fetchData();
    fetchMVP();
    updateOfflineBadge();
  });
})();