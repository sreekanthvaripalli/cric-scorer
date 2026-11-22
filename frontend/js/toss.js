/**
 * Cric-Scorer — Toss UI Controller
 *
 * Handles the online toss flow:
 * 1. Phase 1: Initiator calls heads or tails
 * 2. Phase 2: System flips coin, shows result and winner
 * 3. Phase 3: Winning team chooses bat or field
 */

const API_BASE = window.location.origin;
let matchData = null;

const tossPhase1 = document.getElementById('toss-phase-1');
const tossPhase2 = document.getElementById('toss-phase-2');
const tossPhase3 = document.getElementById('toss-phase-3');
const callHeadsBtn = document.getElementById('call-heads');
const callTailsBtn = document.getElementById('call-tails');
const tossCallStatus = document.getElementById('toss-call-status');
const tossResultDisplay = document.getElementById('toss-result-display');
const tossWinner = document.getElementById('toss-winner');
const decisionBatBtn = document.getElementById('decision-bat');
const decisionFieldBtn = document.getElementById('decision-field');
const tossDecisionStatus = document.getElementById('toss-decision-status');
const finalWinner = document.getElementById('final-winner');
const finalDecision = document.getElementById('final-decision');
const tossFinalStatus = document.getElementById('toss-final-status');

async function fetchMatch() {
    try {
        const response = await fetch(`${API_BASE}/matches/${matchId}/public`);
        if (!response.ok) {
            throw new Error(`Failed to fetch match: ${response.status}`);
        }
        matchData = await response.json();
        updateMatchInfo();
    } catch (error) {
        console.error('Error fetching match:', error);
        document.getElementById('scorecard-info').textContent = `Error: ${error.message}`;
    }
}

function updateMatchInfo() {
    document.getElementById('match-name').textContent = matchData.name;
    document.getElementById('format-name').textContent = matchData.format;
    document.getElementById('overs-per-innings').textContent = matchData.overs_per_innings;
    document.getElementById('status-text').textContent = matchData.status;
    document.getElementById('team-a').textContent = matchData.team_a_name;
    document.getElementById('team-b').textContent = matchData.team_b_name;

    if (matchData.status === 'created') {
        tossPhase1.classList.remove('hidden');
        return;
    }
    fetchToss();
}

async function fetchToss() {
    try {
        const response = await fetch(`${API_BASE}/matches/${matchId}/toss`);
        if (!response.ok) {
            throw new Error(`Failed to fetch toss: ${response.status}`);
        }
        const tossData = await response.json();

        if (tossData.status === 'pending') {
            tossPhase1.classList.remove('hidden');
            tossPhase2.classList.add('hidden');
            tossPhase3.classList.add('hidden');
            tossCallStatus.textContent = 'Waiting for toss call...';
            return;
        }

        if (tossData.coin_result) {
            tossPhase1.classList.add('hidden');
            tossPhase2.classList.remove('hidden');
            tossPhase3.classList.add('hidden');

            tossResultDisplay.textContent = `Coin landed: <strong>${tossData.coin_result}</strong>`;
            tossResultDisplay.className = `toss-result toss-result--${tossData.coin_result}`;

            const winnerName = tossData.winner_team_id === 1 ? matchData.team_a_name : matchData.team_b_name;
            tossWinner.textContent = `Winning team: ${winnerName}`;

            decisionBatBtn.disabled = false;
            decisionFieldBtn.disabled = false;
            tossDecisionStatus.textContent = 'Choose whether the winning team will bat or field';
        } else {
            tossPhase1.classList.add('hidden');
            tossPhase2.classList.add('hidden');
            tossPhase3.classList.add('hidden');
            tossCallStatus.textContent = `Toss called: ${tossData.initiator_call}`;
        }
    } catch (error) {
        console.error('Error fetching toss:', error);
        tossCallStatus.textContent = `Error: ${error.message}`;
    }
}

async function callToss(call) {
    if (matchData.status !== 'created') {
        tossCallStatus.textContent = 'Cannot call toss - match is not in created status';
        return;
    }

    const btn = call === 'heads' ? callHeadsBtn : callTailsBtn;
    btn.disabled = true;
    btn.classList.add('shake');
    tossCallStatus.textContent = `Calling ${call}...`;

    try {
        const response = await fetch(`${API_BASE}/matches/${matchId}/toss/call`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ call: call }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Failed to call toss: ${response.status}`);
        }

        tossCallStatus.textContent = `✅ Toss called: ${call}`;
        callHeadsBtn.disabled = true;
        callTailsBtn.disabled = true;
        await fetchToss();
    } catch (error) {
        console.error('Error calling toss:', error);
        tossCallStatus.textContent = `Error: ${error.message}`;
        btn.disabled = false;
        btn.classList.remove('shake');
    }
}

async function flipCoin() {
    try {
        const response = await fetch(`${API_BASE}/matches/${matchId}/toss/flip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Failed to flip coin: ${response.status}`);
        }

        const result = await response.json();
        tossCallStatus.textContent = `✅ Coin flipped: ${result.coin_result}`;

        tossResultDisplay.textContent = `Coin landed: <strong>${result.coin_result}</strong>`;
        tossResultDisplay.className = `toss-result toss-result--${result.coin_result}`;

        const winnerName = result.winner_team_id === 1 ? matchData.team_a_name : matchData.team_b_name;
        tossWinner.textContent = `Winning team: ${winnerName}`;

        decisionBatBtn.disabled = false;
        decisionFieldBtn.disabled = false;
        tossDecisionStatus.textContent = 'Choose whether the winning team will bat or field';
    } catch (error) {
        console.error('Error flipping coin:', error);
        tossCallStatus.textContent = `Error: ${error.message}`;
    }
}

async function decideBatOrField(decision) {
    decisionBatBtn.disabled = true;
    decisionFieldBtn.disabled = true;
    tossDecisionStatus.textContent = `Selecting ${decision}...`;

    try {
        const response = await fetch(`${API_BASE}/matches/${matchId}/toss/flip/result`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ toss_decision: decision }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Failed to record decision: ${response.status}`);
        }

        const result = await response.json();
        tossDecisionStatus.textContent = `✅ ${decision} selected by ${result.winner_team_id === 1 ? matchData.team_a_name : matchData.team_b_name}`;

        tossPhase1.classList.add('hidden');
        tossPhase2.classList.add('hidden');
        tossPhase3.classList.remove('hidden');

        finalWinner.textContent = result.winner_team_id === 1 ? matchData.team_a_name : matchData.team_b_name;
        finalDecision.textContent = result.toss_decision === 'bat' ? '🏏 Bat' : '🧢 Field';
        tossFinalStatus.textContent = '✅ Toss locked! Scoring can begin.';

        document.getElementById('scorecard-info').textContent =
            `First innings: ${matchData.team_a_name} (bat) vs ${matchData.team_b_name} (field) — ${result.toss_decision}`;
    } catch (error) {
        console.error('Error deciding bat/field:', error);
        tossDecisionStatus.textContent = `Error: ${error.message}`;
        decisionBatBtn.disabled = false;
        decisionFieldBtn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    matchId = params.get('match_id') || window.location.pathname.split('/').pop();

    if (!matchId) {
        document.getElementById('scorecard-info').textContent = 'Match ID not found in URL';
        return;
    }

    fetchMatch();

    callHeadsBtn.addEventListener('click', () => callToss('heads'));
    callTailsBtn.addEventListener('click', () => callToss('tails'));

    decisionBatBtn.addEventListener('click', () => decideBatOrField('bat'));
    decisionFieldBtn.addEventListener('click', () => decideBatOrField('field'));
});
