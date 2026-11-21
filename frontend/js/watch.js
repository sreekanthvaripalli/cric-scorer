/**
 * Cric-Scorer — Watch Controller
 * Online watch page with auto-refresh
 */

(function () {
  "use strict";

  const API_BASE = window.location.origin;
  let matchId = null;
  let isConnected = true;

  const matchName = document.getElementById("match-name");
  const status = document.getElementById("status");
  const teamA = document.getElementById("team-a");
  const teamB = document.getElementById("team-b");
  const format = document.getElementById("format");
  const overs = document.getElementById("overs");
  const teamARuns = document.getElementById("team-a-runs");
  const teamBRuns = document.getElementById("team-b-runs");
  const teamAWickets = document.getElementById("team-a-wickets");
  const teamBWickets = document.getElementById("team-b-wickets");
  const teamAOvers = document.getElementById("team-a-overs");
  const teamBOvers = document.getElementById("team-b-overs");
  const ballFeed = document.getElementById("ball-feed");
  const tossBox = document.getElementById("toss-box");
  const tossContent = document.getElementById("toss-content");
  const connectionCount = document.getElementById("connection-count");
  const lastUpdate = document.getElementById("last-update");

  function connectWebSocket() {
    if (!matchId) return null;
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = wsProtocol + "//" + window.location.host + "/ws/match/" + matchId;
    const ws = new WebSocket(wsUrl);
    ws.onopen = function() { isConnected = true; updatePresence(true); };
    ws.onmessage = function(event) {
      try {
        const data = JSON.parse(event.data);
        handleLiveUpdate(data);
        lastUpdate.textContent = new Date().toLocaleTimeString();
      } catch (e) { console.error("Invalid WS msg:", e); }
    };
    ws.onclose = function(event) {
      isConnected = false;
      updatePresence(false);
      if (event.code !== 1000) {
        setTimeout(connectWebSocket, 3000);
      }
    };
    ws.onerror = function() {};
    return ws;
  }

  function handleLiveUpdate(data) {
    if (data.match) {
      matchName.textContent = data.match.name || matchName.textContent;
      teamA.textContent = data.match.team_a_name || teamA.textContent;
      teamB.textContent = data.match.team_b_name || teamB.textContent;
      format.textContent = data.match.format || format.textContent;
      overs.textContent = data.match.overs_per_innings || overs.textContent;
      status.textContent = data.match.status || status.textContent;
      status.className = "status " + (data.match.status === "in_progress" ? "live" : "idle");
    }
    if (data.ball) {
      teamARuns.textContent = data.ball.striker_runs || "";
      teamBRuns.textContent = data.ball.non_striker_runs || "";
      if (data.ball.wickets) {
        teamAWickets.textContent = data.ball.wickets_a || "";
        teamBWickets.textContent = data.ball.wickets_b || "";
      }
      const totalOvers = data.ball.overs || parseFloat(overs.textContent);
      if (totalOvers) {
        teamAOvers.textContent = totalOvers.toFixed(1);
        teamBOvers.textContent = totalOvers.toFixed(1);
      }
      if (data.ball.delivery) {
        addBallToFeed(data.ball);
        ballFeed.scrollTop = ballFeed.scrollHeight;
      }
    }
    if (data.toss) { updateTossDisplay(data.toss); }
    if (data.presence) { updatePresence(data.presence.is_connected, data.presence.connections || 1); }
  }

  function addBallToFeed(ball) {
    const item = document.createElement("div");
    item.className = "ball-item";
    let runsText = "";
    if (ball.runs_batter > 0) {
      runsText += 'Runs: <span class="ball-runs">+' + ball.runs_batter + '</span>';
    }
    if (ball.extra_type) {
      const map = { nb: "No ball", wd: "Wide", bye: "Bye", legbye: "Leg bye", penalty: "Penalty" };
      runsText += ' | <span class="ball-decision">' + (map[ball.extra_type] || ball.extra_type) + '</span>';
    }
    if (ball.boundary_type) {
      runsText += ' | <span class="ball-runs">Boundary ' + ball.boundary_type + '</span>';
    }
    if (ball.is_wicket) {
      runsText += ' | <span class="ball-wicket">' + (ball.dismissal_mode || "out") + '</span>';
    }
    item.innerHTML =
      '<div class="ball-time">' + new Date().toLocaleTimeString() + '</div>' +
      '<div class="ball-side">' + ball.striker_id + ' (' + (ball.boundary_type ? 'c.' : '·') + ')</div>' +
      '<div class="ball-runs">' + runsText + '</div>';
    const list = document.getElementById("ball-feed");
    if (list) {
      list.insertBefore(item, list.firstChild);
      while (list.children.length > 10) list.removeChild(list.lastChild);
    }
  }

  function updateTossDisplay(toss) {
    if (tossContent) {
      tossContent.innerHTML =
        "<p>Winner: " + (toss.winner_team_id === 1 ? "Team A" : "Team B") + "</p>" +
        "<p>Result: " + toss.coin_result + "</p>" +
        "<p>Decision: " + (toss.toss_decision || "Pending") + "</p>";
    }
  }

  function updatePresence(isConnected, count) {
    connectionCount.textContent = typeof count === "number" ? count : 0;
    status.className = isConnected ? "status live" : "status idle";
  }

  document.addEventListener("DOMContentLoaded", function() {
    matchId = window.location.pathname.split("/").pop();
    connectWebSocket();
  });
})();