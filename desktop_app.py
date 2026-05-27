"""
desktop_app.py — SentinelAI Desktop Application
Lightweight desktop shell using Flask + system tray
Launches backend, provides UI, system tray controls
"""
import os
import sys
import subprocess
import threading
import webbrowser
import logging
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import pystray
from PIL import Image, ImageDraw
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import db
import learning_memory as lm
import queue_manager as qm
import worker_manager as wm
import watchdog as wd
import health_monitor as hm
import orchestration as orch
from internet_runtime import get_research_runtime
from memory.filesystem_index import get_filesystem_indexer
from memory.persistent_memory import get_memory
from model_router import get_model_router
from reflection import ReflectionEngine
from tool_registry import get_tool_registry
from executor import run_executor
from scanner import scan_github_issues
from openclaw_integration import OpenClawCommandRouter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
CORS(app)

# Global state
backend_state = {
    "running": False,
    "paused": False,
    "active_tasks": [],
    "ollama_status": "unknown",
    "last_scan": None,
    "total_earnings": 0.0
}

# Authentication
AUTH_TOKEN = os.getenv("SENTINELAI_AUTH_TOKEN", "sentinelai_default_token_change_me")


def verify_auth_token(token: str) -> bool:
    """Verify authentication token."""
    if not token:
        return False
    # Remove 'Bearer ' prefix if present
    if token.startswith('Bearer '):
        token = token[7:]
    return token == AUTH_TOKEN


# ─── System Tray Icon ─────────────────────────────────────────────────────────

def create_tray_icon():
    """Create a simple system tray icon."""
    # Create a simple icon (dark circle with 'S')
    width = 64
    height = 64
    image = Image.new('RGB', (width, height), color='#1a1a2e')
    draw = ImageDraw.Draw(image)
    
    # Draw 'S' for Sentinel
    draw.ellipse([8, 8, 56, 56], fill='#16213e', outline='#0f3460')
    draw.text((20, 18), 'S', fill='#00d4ff')
    
    return image


def on_quit(icon, item):
    """Quit the application."""
    logger.info("Quitting SentinelAI...")
    backend_state["running"] = False
    icon.stop()
    os._exit(0)


def on_open_dashboard(icon, item):
    """Open dashboard in browser."""
    webbrowser.open('http://localhost:5001')


def on_pause_resume(icon, item):
    """Toggle pause/resume."""
    backend_state["paused"] = not backend_state["paused"]
    status = "paused" if backend_state["paused"] else "resumed"
    logger.info(f"SentinelAI {status}")


def create_system_tray():
    """Create system tray icon with menu."""
    icon_image = create_tray_icon()
    
    menu = pystray.Menu(
        pystray.MenuItem('Open Dashboard', on_open_dashboard),
        pystray.MenuItem('Pause/Resume', on_pause_resume),
        pystray.MenuItem('Quit', on_quit)
    )
    
    icon = pystray.Icon('SentinelAI', icon_image, 'SentinelAI', menu)
    return icon


# ─── Flask Routes ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Main dashboard."""
    return render_template('desktop_dashboard.html')


@app.route('/mobile')
def mobile():
    """Mobile-optimized dashboard."""
    return render_template('mobile_dashboard.html')


@app.route('/api/status')
def api_status():
    """Get current system status."""
    # Check Ollama
    try:
        import httpx
        response = httpx.get('http://127.0.0.1:11434/api/tags', timeout=2)
        backend_state["ollama_status"] = "running" if response.status_code == 200 else "error"
    except Exception:
        backend_state["ollama_status"] = "offline"
    
    # Get earnings
    try:
        earnings = db.get_earnings_summary()
        backend_state["total_earnings"] = earnings.get("confirmed_earnings", 0.0)
    except Exception:
        pass
    
    return jsonify({
        "running": backend_state["running"],
        "paused": backend_state["paused"],
        "ollama_status": backend_state["ollama_status"],
        "active_tasks": len(backend_state["active_tasks"]),
        "total_earnings": backend_state["total_earnings"],
        "last_scan": backend_state["last_scan"]
    })


@app.route('/api/tasks')
def api_tasks():
    """Get active tasks."""
    try:
        opportunities = db.list_opportunities(status="in_progress", limit=10)
        return jsonify({"tasks": opportunities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/pending-approvals')
def api_pending_approvals():
    """Get tasks pending approval."""
    try:
        opportunities = db.list_opportunities(status="ready", limit=10)
        return jsonify({"pending": opportunities})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/logs')
def api_logs():
    """Get recent logs."""
    try:
        logs = db.get_recent_logs(limit=50)
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/earnings')
def api_earnings():
    """Get earnings summary."""
    try:
        earnings = db.get_earnings_summary()
        return jsonify(earnings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/approve/<int:opp_id>', methods=['POST'])
def api_approve(opp_id):
    """Approve a pending task."""
    try:
        # Check auth token
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        # Update opportunity status
        db.update_opportunity_status(opp_id, "approved")
        db.log_event("task_approved", f"Task #{opp_id} approved via API", opp_id)
        logger.info(f"Task #{opp_id} approved")
        return jsonify({"status": "approved", "opportunity_id": opp_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/reject/<int:opp_id>', methods=['POST'])
def api_reject(opp_id):
    """Reject a pending task."""
    try:
        # Check auth token
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        # Update opportunity status
        db.update_opportunity_status(opp_id, "rejected")
        db.log_event("task_rejected", f"Task #{opp_id} rejected via API", opp_id)
        logger.info(f"Task #{opp_id} rejected")
        return jsonify({"status": "rejected", "opportunity_id": opp_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/pause', methods=['POST'])
def api_pause():
    """Pause operations."""
    # Check auth token
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    backend_state["paused"] = True
    logger.info("Operations paused")
    return jsonify({"status": "paused"})


@app.route('/api/resume', methods=['POST'])
def api_resume():
    """Resume operations."""
    # Check auth token
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    backend_state["paused"] = False
    logger.info("Operations resumed")
    return jsonify({"status": "running"})


@app.route('/api/emergency-stop', methods=['POST'])
def api_emergency_stop():
    """Emergency stop all operations."""
    # Check auth token
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    backend_state["running"] = False
    backend_state["paused"] = True
    logger.warning("EMERGENCY STOP activated")
    return jsonify({"status": "stopped"})


@app.route('/api/openclaw/command', methods=['POST'])
def api_openclaw_command():
    """
    OpenClaw command endpoint.
    Allows OpenClaw to control SentinelAI through safe command routing.
    """
    try:
        data = request.get_json()
        command = data.get('command')
        parameters = data.get('parameters', {})
        auth_token = request.headers.get('Authorization')
        
        if not command:
            return jsonify({"error": "command required"}), 400
        
        # Initialize router with auth token
        router = OpenClawCommandRouter(auth_token=auth_token)
        
        # Route command
        result = router.route_command(command, parameters)
        
        return jsonify(result)
    except Exception as e:
        logger.exception("Error processing OpenClaw command")
        return jsonify({"error": str(e)}), 500


@app.route('/api/openclaw/commands', methods=['GET'])
def api_openclaw_commands():
    """Get list of available OpenClaw commands."""
    from openclaw_integration import OPENCLAW_COMMANDS, BLOCKED_COMMANDS
    
    return jsonify({
        "available_commands": OPENCLAW_COMMANDS,
        "blocked_commands": BLOCKED_COMMANDS
    })


# ─── Phase 7: Always-On Operations API Endpoints ──────────────────────────────

@app.route('/api/system/health')
def api_system_health():
    """Get system health metrics."""
    try:
        monitor = hm.get_monitor()
        return jsonify(monitor.get_current_metrics())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/health/summary')
def api_system_health_summary():
    """Get health metrics summary."""
    try:
        monitor = hm.get_monitor()
        return jsonify(monitor.get_metrics_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/workers')
def api_system_workers():
    """Get worker status."""
    try:
        manager = wm.get_manager()
        return jsonify({
            "workers": manager.get_all_worker_status(),
            "stats": manager.get_stats()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/queue')
def api_system_queue():
    """Get queue status."""
    try:
        stats = qm.get_queue_stats()
        tasks = qm.list_tasks(limit=50)
        return jsonify({
            "stats": stats,
            "tasks": tasks
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/watchdog')
def api_system_watchdog():
    """Get watchdog status."""
    try:
        watchdog = wd.get_watchdog()
        return jsonify(watchdog.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/integrity')
def api_system_integrity():
    """Verify system integrity."""
    try:
        status = wd.verify_system_integrity()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/pause', methods=['POST'])
def api_system_pause():
    """Pause all workers."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        manager = wm.get_manager()
        manager.pause_all()
        return jsonify({"status": "paused"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/resume', methods=['POST'])
def api_system_resume():
    """Resume all workers."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        manager = wm.get_manager()
        manager.resume_all()
        return jsonify({"status": "running"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/system/restart-workers', methods=['POST'])
def api_system_restart_workers():
    """Restart all workers."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        manager = wm.get_manager()
        for worker_id in list(manager.workers.keys()):
            manager.restart_worker(worker_id)
        
        return jsonify({"status": "restarted", "count": len(manager.workers)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Learning Memory API Endpoints ────────────────────────────────────────────

@app.route('/api/learning/summary')
def api_learning_summary():
    """Get learning system summary and analytics."""
    try:
        summary = lm.get_learning_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/recommendations')
def api_learning_recommendations():
    """Get AI-generated recommendations based on learned data."""
    try:
        recommendations = lm.get_recommendations()
        return jsonify({"recommendations": recommendations})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/platform-performance')
def api_platform_performance():
    """Get platform performance metrics."""
    try:
        platforms = lm.get_all_platform_performance()
        return jsonify({"platforms": platforms})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/patterns')
def api_learning_patterns():
    """Get learned patterns."""
    try:
        pattern_type = request.args.get('type', 'keyword')
        min_confidence = float(request.args.get('min_confidence', 0.6))
        patterns = lm.get_patterns_by_type(pattern_type, min_confidence)
        return jsonify({"patterns": patterns})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/complexity-accuracy')
def api_complexity_accuracy():
    """Get complexity estimation accuracy metrics."""
    try:
        accuracy = lm.get_complexity_accuracy()
        return jsonify(accuracy)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/events')
def api_learning_events():
    """Get recent learning events."""
    try:
        limit = int(request.args.get('limit', 50))
        events = lm.get_recent_learning_events(limit)
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/learning/record-outcome', methods=['POST'])
def api_record_outcome():
    """Record task outcome for learning (requires auth)."""
    try:
        # Check auth token
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        
        data = request.get_json()
        opportunity_id = data.get('opportunity_id')
        success = data.get('success', False)
        actual_complexity = data.get('actual_complexity', 0)
        time_hours = data.get('time_hours', 0)
        earnings = data.get('earnings', 0)
        
        if not opportunity_id:
            return jsonify({"error": "opportunity_id required"}), 400
        
        # Get opportunity details
        opp = db.get_opportunity(opportunity_id)
        if not opp:
            return jsonify({"error": "Opportunity not found"}), 404
        
        # Update platform performance
        lm.update_platform_performance(
            opp['source'],
            success,
            opp['bounty_amount'],
            actual_complexity or opp['complexity_score'],
            earnings
        )
        
        # Extract and learn patterns
        lm.extract_and_learn_patterns(
            opportunity_id,
            opp['title'],
            [],  # Labels not stored in current schema
            opp['repo_url'],
            success,
            actual_complexity,
            time_hours
        )
        
        # Update complexity feedback
        if actual_complexity > 0:
            lm.update_complexity_feedback(
                opportunity_id,
                actual_complexity,
                time_hours,
                success,
                data.get('notes', '')
            )
        
        logger.info(f"Recorded learning outcome for opportunity #{opportunity_id}")
        return jsonify({"status": "recorded", "opportunity_id": opportunity_id})
    except Exception as e:
        logger.exception("Error recording learning outcome")
        return jsonify({"error": str(e)}), 500


# ─── Orchestration Runtime API Endpoints ─────────────────────────────────────

@app.route('/api/orchestration/status')
def api_orchestration_status():
    """Get Sentinel orchestration runtime status."""
    try:
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows')
def api_orchestration_workflows():
    """List orchestration workflows."""
    try:
        status = request.args.get('status')
        limit = int(request.args.get('limit', 100))
        orchestrator = orch.get_orchestrator()
        return jsonify({"workflows": orchestrator.list_workflows(status=status, limit=limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>')
def api_orchestration_workflow(workflow_id):
    """Get a single orchestration workflow."""
    try:
        orchestrator = orch.get_orchestrator()
        workflow = orchestrator.get_workflow(workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        return jsonify(workflow)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows', methods=['POST'])
def api_orchestration_submit():
    """Submit a new supervised orchestration workflow."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json() or {}
        goal = data.get('goal')
        if not goal:
            return jsonify({"error": "goal required"}), 400

        orchestrator = orch.get_orchestrator()
        result = orchestrator.submit_workflow(
            goal=goal,
            workflow_type=data.get('workflow_type', 'general'),
            requires_approval=bool(data.get('requires_approval', True)),
            max_retries=int(data.get('max_retries', 3)),
            enqueue=bool(data.get('enqueue', True)),
        )
        return jsonify(result), 201
    except Exception as e:
        logger.exception("Error submitting orchestration workflow")
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>/run', methods=['POST'])
def api_orchestration_run(workflow_id):
    """Run or resume a workflow through the orchestration graph."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.run_workflow(workflow_id))
    except Exception as e:
        logger.exception("Error running orchestration workflow")
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/approvals')
def api_orchestration_approvals():
    """List workflows waiting for human approval."""
    try:
        orchestrator = orch.get_orchestrator()
        return jsonify({"pending": orchestrator.pending_approvals()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>/approve', methods=['POST'])
def api_orchestration_approve(workflow_id):
    """Approve an orchestration workflow checkpoint."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.approve_workflow(
            workflow_id,
            decided_by=data.get('decided_by', 'user'),
            reason=data.get('reason', ''),
        ))
    except Exception as e:
        logger.exception("Error approving orchestration workflow")
        return jsonify({"error": str(e)}), 500


@app.route('/api/orchestration/workflows/<int:workflow_id>/reject', methods=['POST'])
def api_orchestration_reject(workflow_id):
    """Reject an orchestration workflow checkpoint."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        orchestrator = orch.get_orchestrator()
        return jsonify(orchestrator.reject_workflow(
            workflow_id,
            decided_by=data.get('decided_by', 'user'),
            reason=data.get('reason', ''),
        ))
    except Exception as e:
        logger.exception("Error rejecting orchestration workflow")
        return jsonify({"error": str(e)}), 500


# ─── Intelligence Runtime API Endpoints ──────────────────────────────────────

@app.route('/api/memory/search')
def api_memory_search():
    """Search persistent vector memory."""
    try:
        namespace = request.args.get('namespace', 'workflow')
        query = request.args.get('q', '')
        limit = int(request.args.get('limit', 5))
        if not query:
            return jsonify({"error": "q required"}), 400
        return jsonify({"results": get_memory().recall(namespace, query, limit)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/memory/remember', methods=['POST'])
def api_memory_remember():
    """Persist a memory item. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        namespace = data.get('namespace', 'project')
        content = data.get('content')
        if not content:
            return jsonify({"error": "content required"}), 400
        memory_id = get_memory().remember(namespace, content, data.get('metadata') or {})
        return jsonify({"memory_id": memory_id, "namespace": namespace}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/research/search', methods=['POST'])
def api_research_search():
    """Run live internet research through configured providers. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        query = data.get('query')
        if not query:
            return jsonify({"error": "query required"}), 400
        result = get_research_runtime().search(
            query,
            limit=int(data.get('limit', 5)),
            persist=bool(data.get('persist', True)),
        )
        return jsonify(result)
    except Exception as e:
        logger.exception("Research search failed")
        return jsonify({"error": str(e)}), 500


@app.route('/api/filesystem/index', methods=['POST'])
def api_filesystem_index():
    """Index a workspace for persistent filesystem awareness. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json() or {}
        root = data.get('root')
        if not root:
            return jsonify({"error": "root required"}), 400
        result = get_filesystem_indexer().index_workspace(root, int(data.get('max_files', 1000)))
        return jsonify(result)
    except Exception as e:
        logger.exception("Filesystem indexing failed")
        return jsonify({"error": str(e)}), 500


@app.route('/api/model-router/route', methods=['POST'])
def api_model_route():
    """Route a task to the best configured model."""
    try:
        data = request.get_json() or {}
        selection = get_model_router().route(
            data.get('task_type', 'general'),
            data.get('prompt', ''),
            bool(data.get('prefer_local', True)),
        )
        return jsonify(selection)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/model-router/status')
def api_model_router_status():
    """Get model routing capability registry."""
    try:
        return jsonify(get_model_router().status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tools')
def api_tools():
    """List supervised tools."""
    try:
        return jsonify({"tools": get_tool_registry().list_tools()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tools/run', methods=['POST'])
def api_tool_run():
    """Run a supervised tool. Mutating/terminal tools require auth."""
    try:
        data = request.get_json() or {}
        name = data.get('name')
        args = data.get('args') or {}
        if not name:
            return jsonify({"error": "name required"}), 400
        tool = get_tool_registry().tools.get(name)
        if not tool:
            return jsonify({"error": "Unknown tool"}), 404
        if tool.requires_approval:
            auth_token = request.headers.get('Authorization')
            if not verify_auth_token(auth_token):
                return jsonify({"error": "Unauthorized"}), 401
        result = tool.run(**args)
        return jsonify(result.__dict__)
    except Exception as e:
        logger.exception("Tool run failed")
        return jsonify({"error": str(e)}), 500


@app.route('/api/reflection/workflows/<int:workflow_id>', methods=['POST'])
def api_reflect_workflow(workflow_id):
    """Run a reflection pass on a workflow. Requires auth."""
    try:
        auth_token = request.headers.get('Authorization')
        if not verify_auth_token(auth_token):
            return jsonify({"error": "Unauthorized"}), 401
        workflow = orch.get_orchestrator().get_workflow(workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        return jsonify(ReflectionEngine().reflect(workflow))
    except Exception as e:
        logger.exception("Reflection failed")
        return jsonify({"error": str(e)}), 500


# ─── Backend Launcher ─────────────────────────────────────────────────────────

def run_flask_app():
    """Run Flask app in background thread."""
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)


def start_backend():
    """Start the SentinelAI backend."""
    logger.info("Starting SentinelAI backend...")
    
    # Initialize database
    db.init_db()
    
    # Initialize learning memory system
    try:
        lm.initialize_learning_system()
        logger.info("Learning memory system initialized")
    except Exception as e:
        logger.warning(f"Learning memory initialization failed: {e}")
    
    # Initialize queue system
    try:
        qm.initialize_queue()
        logger.info("Task queue initialized")
    except Exception as e:
        logger.warning(f"Queue initialization failed: {e}")

    # Initialize orchestration runtime
    try:
        orchestrator = orch.initialize_orchestration()
        recovered = orchestrator.recover_workflows()
        logger.info(f"Orchestration runtime initialized (recovered={recovered})")
    except Exception as e:
        logger.warning(f"Orchestration initialization failed: {e}")
    
    # Perform crash recovery
    try:
        wd.recover_from_crash()
        logger.info("Crash recovery completed")
    except Exception as e:
        logger.warning(f"Crash recovery failed: {e}")
    
    # Initialize worker manager
    try:
        max_workers = int(os.getenv("MAX_WORKERS", "3"))
        manager = wm.initialize_workers(max_workers)
        manager.register_handler("orchestration_workflow", orch.get_orchestrator().handle_queue_task)
        logger.info(f"Worker manager initialized (max_workers={max_workers})")
    except Exception as e:
        logger.warning(f"Worker manager initialization failed: {e}")
    
    # Initialize watchdog
    try:
        watchdog_interval = int(os.getenv("WATCHDOG_CHECK_INTERVAL", "30"))
        watchdog = wd.initialize_watchdog(watchdog_interval)
        watchdog.start()
        logger.info(f"Watchdog started (interval={watchdog_interval}s)")
    except Exception as e:
        logger.warning(f"Watchdog initialization failed: {e}")
    
    # Initialize health monitor
    try:
        health_interval = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))
        monitor = hm.initialize_health_monitor(health_interval)
        monitor.start()
        logger.info(f"Health monitor started (interval={health_interval}s)")
    except Exception as e:
        logger.warning(f"Health monitor initialization failed: {e}")
    
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    
    backend_state["running"] = True
    logger.info("Backend started on http://localhost:5001")


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def main():
    """Main entry point for desktop app."""
    logger.info("=" * 80)
    logger.info("SENTINELAI DESKTOP APPLICATION")
    logger.info("=" * 80)
    
    # Start backend
    start_backend()
    
    # Open dashboard in browser
    webbrowser.open('http://localhost:5001')
    
    # Create and run system tray
    logger.info("Creating system tray icon...")
    icon = create_system_tray()
    
    logger.info("SentinelAI is now running. Check system tray for controls.")
    icon.run()


if __name__ == "__main__":
    main()
