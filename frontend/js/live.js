/**
 * Cric-Scorer — Live Score JavaScript
 *
 * Real-time score broadcasting via WebSocket.
 */

(function () {
    'use strict';

    const matchId = window.location.pathname.split('/').pop();

    const matchName = document.getElementById('match-name');
    const teamA = document.getElementById('team-a');
    const teamB = document.getElementById('team-b');
    const format = document.getElementById('format');
    const overs = document.getElementById('overs');
    const status = document.getElementById('status');

    const teamARuns = document.getElementById('team-a-runs');
    const teamBRuns = document.getElementById('team-b-runs');
    const teamAWickets = document.getElementById('team-a-wickets');
    const teamBWickets = document.getElementById('team-b-wickets');
    const teamAOvers = document.getElementById('team-a-overs');
    const teamBOvers = document.getElementById('team-b-overs');

    const ballFeed = document.getElementById('ball-feed');
    const tossBox = document.getElementById('toss-box');
    const tossContent = document.getElementById('toss-content');
    const connectionCount = document.getElementById('connection-count');
    const lastUpdate = document.getElementById('last-update');

    let ws = null;
    let reconnecting = false;
    let reconnectTimer = null;
    let currentMatchId = null;

    const OPTIONS = {
        wsUrl: null,
        pollInterval: 15000,
        reconnectDelay: 3000,
        maxReconnectAttempts: 10,
    };

    function connectWebSocket() {
        if (!matchId) {
            console.error('No match ID provided');
            document.getElementById('ball-feed').innerHTML = '<p class="placeholder">No match ID provided. Use /watch/{id} to view a match.</p>';
            return;
        }

        currentMatchId = matchId;
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        OPTIONS.wsUrl = `${wsProtocol}//${window.location.host}/ws/match/${matchId}`;

        console.log('Connecting to WebSocket:', OPTIONS.wsUrl);

        try {
            ws = new WebSocket(OPTIONS.wsUrl);
        } catch (e) {
            console.error('WebSocket connection failed:', e);
            ws = null;
        }

        if (ws) {
            ws.onopen = onWebSocketOpen;
            ws.onmessage = onWebSocketMessage;
            ws.onclose = onWebSocketClose;
            ws.onerror = onWebSocketError;
        } else {
            fallbackToPolling();
        }
    }

    function onWebSocketOpen() {
        console.log('WebSocket connected');
        updatePresence(true);
        lastUpdate.textContent = new Date().toLocaleTimeString();
    }

    function onWebSocketMessage(event) {
        try {
            const data = JSON.parse(event.data);
            handleLiveUpdate(data);
            lastUpdate.textContent = new Date().toLocaleTimeString();
        } catch (e) {
            console.error('Invalid WebSocket message:', e);
        }
    }

    function onWebSocketClose(event) {
        console.log('WebSocket closed. Code:', event.code, 'Reason:', event.reason);
        updatePresence(false);
        if (reconnecting) {
            return;
        }
        if (event.code === 1000) {
            return;
        }
        if (OPTIONS.maxReconnectAttempts > 0) {
            reconnecting = true;
            reconnectTimer = setTimeout(() => {
                reconnecting = false;
                connectWebSocket();
            }, OPTIONS.reconnectDelay);
        }
    }

    function onWebSocketError(error) {
        console.error('WebSocket error:', error);
    }

    function fallbackToPolling() {
        console.log('WebSocket unavailable, falling back to polling');
        updatePresence(false);
        pollMatchState();
        setInterval(pollMatchState, OPTIONS.pollInterval);
    }

    function pollMatchState() {
        const params = new URLSearchParams(window.location.search);
        const matchId = params.get('match_id');
        if (!matchId) return;

        fetch(`/matches/${matchId}/live`)
            .then(response => response.json())
            .then(data => {
                lastUpdate.textContent = new Date().toLocaleTimeString();
                handleLiveUpdate(data);
            })
            .catch(error => {
                console.error('Polling error:', error);
            });
    }

    function handleLiveUpdate(data) {
        if (data.match) {
            matchName.textContent = data.match.name || matchName.textContent;
            teamA.textContent = data.match.team_a_name || teamA.textContent;
            teamB.textContent = data.match.team_b_name || teamB.textContent;
            format.textContent = data.match.format || format.textContent;
            overs.textContent = data.match.overs_per_innings || overs.textContent;
            status.textContent = data.match.status || status.textContent;
            status.className = 'status ' + (data.match.status === 'in_progress' ? 'live' : 'idle');
        }

        if (data.ball) {
            teamARuns.textContent = data.ball.striker_runs || teamARuns.textContent;
            teamBRuns.textContent = data.ball.non_striker_runs || teamBRuns.textContent;

            if (data.ball.wickets) {
                teamAWickets.textContent = data.ball.wickets_a || teamAWickets.textContent;
                teamBWickets.textContent = data.ball.wickets_b || teamBWickets.textContent;
            }
        }

        const totalOvers = (data.ball && data.ball.overs) ? data.ball.overs : parseFloat(document.getElementById('overs').textContent);
        if (totalOvers) {
            teamAOvers.textContent = totalOvers.toFixed(1);
            teamBOvers.textContent = totalOvers.toFixed(1);
        }

        if (data.ball && data.ball.delivery) {
            addBallToFeed(data.ball);
            ballFeed.scrollTop = ballFeed.scrollHeight;
        }

        if (data.toss) {
            updateTossDisplay(data.toss);
        }

        if (data.presence) {
            updatePresence(data.presence.is_connected, data.presence.connections || 1);
        }
    }

    function addBallToFeed(ball) {
        const item = document.createElement('div');
        item.className = 'ball-item';

        let runsText = '';
        if (ball.runs_batter > 0) {
            runsText = `Runs: <span class="ball-runs">+${ball.runs_batter}</span>`;
        }
        if (ball.extra_type) {
            const extraMap = { nb: 'No ball', wd: 'Wide', bye: 'Bye', legbye: 'Leg bye', penalty: 'Penalty' };
            runsText += ` | <span class="ball-decision">${extraMap[ball.extra_type] || ball.extra_type}</span>`;
        }
        if (ball.boundary_type) {
            runsText += ` | <span class="ball-runs">Boundary ${ball.boundary_type}</span>`;
        }
        if (ball.is_wicket) {
            const mode = ball.dismissal_mode || 'out';
            runsText += ` | <span class="ball-wicket">${mode}</span>`;
        }

        const dismissed = ball.dismissal_mode ? 'D' : '·';
        const notation = ball.boundary_type ? `c.${dismissed} b.${dismissed}` : `${dismissed}${dismissed}`;

        item.innerHTML = `
            <div class="ball-time">${new Date().toLocaleTimeString()}</div>
            <div class="ball-side">${ball.striker_id} (${notation})</div>
            <div class="ball-runs">${runsText}</div>
        `;

        const list = document.getElementById('ball-feed');
        list.insertBefore(item, list.firstChild);

        while (list.children.length > 10) {
            list.removeChild(list.lastChild);
        }
    }

    function updateTossDisplay(toss) {
        const container = document.getElementById('toss-content');
        container.innerHTML = `
            <p><strong>Winner: </strong>${toss.winner_team_id === 1 ? 'Team A' : 'Team B'}</p>
            <p><strong>Result: </strong>${toss.coin_result}</p>
            <p><strong>Decision: </strong>${toss.toss_decision || 'Pending'}</p>
        `;
    }

    function updatePresence(isConnected, count) {
        connectionCount.textContent = typeof count === 'number' ? count : 0;
        status.className = isConnected ? 'status live' : 'status idle';
    }

    // Initialize
    document.addEventListener('DOMContentLoaded', () => {
        connectWebSocket();
    });
})();
