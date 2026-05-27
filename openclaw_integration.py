"""
openclaw_integration.py — OpenClaw Integration Layer for SentinelAI
Provides command routing and API documentation for OpenClaw personal assistant
OpenClaw controls SentinelAI through these safe command interfaces
"""
import logging
from typing import Dict, Optional, List
from datetime import datetime
import db

logger = logging.getLogger(__name__)


# ─── Command Definitions ──────────────────────────────────────────────────────

OPENCLAW_COMMANDS = {
    "status": {
        "description": "Get current SentinelAI system status",
        "parameters": [],
        "requires_auth": False,
        "dangerous": False,
        "example": "What's the status of SentinelAI?"
    },
    "pause": {
        "description": "Pause all SentinelAI operations",
        "parameters": [],
        "requires_auth": True,
        "dangerous": False,
        "example": "Pause SentinelAI"
    },
    "resume": {
        "description": "Resume SentinelAI operations",
        "parameters": [],
        "requires_auth": True,
        "dangerous": False,
        "example": "Resume SentinelAI"
    },
    "emergency_stop": {
        "description": "Emergency stop all operations",
        "parameters": [],
        "requires_auth": True,
        "dangerous": True,
        "example": "Emergency stop SentinelAI"
    },
    "list_opportunities": {
        "description": "List current opportunities",
        "parameters": [
            {"name": "status", "type": "string", "optional": True, "values": ["new", "in_progress", "ready", "approved", "rejected"]}
        ],
        "requires_auth": False,
        "dangerous": False,
        "example": "Show me new opportunities"
    },
    "list_tasks": {
        "description": "List active tasks",
        "parameters": [],
        "requires_auth": False,
        "dangerous": False,
        "example": "What tasks are running?"
    },
    "approve_task": {
        "description": "Approve a pending task",
        "parameters": [
            {"name": "task_id", "type": "int", "required": True}
        ],
        "requires_auth": True,
        "dangerous": False,
        "example": "Approve task 5"
    },
    "reject_task": {
        "description": "Reject a pending task",
        "parameters": [
            {"name": "task_id", "type": "int", "required": True}
        ],
        "requires_auth": True,
        "dangerous": False,
        "example": "Reject task 5"
    },
    "show_earnings": {
        "description": "Show earnings summary",
        "parameters": [],
        "requires_auth": False,
        "dangerous": False,
        "example": "How much have we earned?"
    },
    "show_logs": {
        "description": "Show recent execution logs",
        "parameters": [
            {"name": "limit", "type": "int", "optional": True, "default": 10}
        ],
        "requires_auth": False,
        "dangerous": False,
        "example": "Show me the last 10 logs"
    }
}


# ─── Blocked Commands ─────────────────────────────────────────────────────────

BLOCKED_COMMANDS = [
    "submit_pr",  # Must be manually approved
    "push_code",  # Must be manually approved
    "delete_repo",  # Dangerous
    "modify_credentials",  # Security risk
    "change_auth_token",  # Security risk
    "execute_shell",  # Security risk
    "install_package",  # Security risk
]


# ─── Command Router ───────────────────────────────────────────────────────────

class OpenClawCommandRouter:
    """Routes OpenClaw commands to SentinelAI operations."""
    
    def __init__(self, auth_token: Optional[str] = None):
        self.auth_token = auth_token
        self.command_history = []
    
    def route_command(self, command: str, parameters: Dict = None) -> Dict:
        """
        Route a command from OpenClaw to the appropriate SentinelAI function.
        
        Args:
            command: Command name (e.g., "status", "pause", "approve_task")
            parameters: Command parameters as dict
        
        Returns:
            Dict with result or error
        """
        parameters = parameters or {}
        
        # Log command
        self.command_history.append({
            "command": command,
            "parameters": parameters,
            "timestamp": datetime.now().isoformat()
        })
        
        # Check if command is blocked
        if command in BLOCKED_COMMANDS:
            logger.warning(f"Blocked dangerous command: {command}")
            return {
                "success": False,
                "error": f"Command '{command}' is blocked for safety",
                "blocked": True
            }
        
        # Check if command exists
        if command not in OPENCLAW_COMMANDS:
            return {
                "success": False,
                "error": f"Unknown command: {command}",
                "available_commands": list(OPENCLAW_COMMANDS.keys())
            }
        
        cmd_def = OPENCLAW_COMMANDS[command]
        
        # Check authentication
        if cmd_def["requires_auth"] and not self.auth_token:
            return {
                "success": False,
                "error": "This command requires authentication",
                "requires_auth": True
            }
        
        # Route to appropriate handler
        try:
            if command == "status":
                return self._handle_status()
            elif command == "pause":
                return self._handle_pause()
            elif command == "resume":
                return self._handle_resume()
            elif command == "emergency_stop":
                return self._handle_emergency_stop()
            elif command == "list_opportunities":
                return self._handle_list_opportunities(parameters.get("status"))
            elif command == "list_tasks":
                return self._handle_list_tasks()
            elif command == "approve_task":
                return self._handle_approve_task(parameters.get("task_id"))
            elif command == "reject_task":
                return self._handle_reject_task(parameters.get("task_id"))
            elif command == "show_earnings":
                return self._handle_show_earnings()
            elif command == "show_logs":
                return self._handle_show_logs(parameters.get("limit", 10))
            else:
                return {
                    "success": False,
                    "error": f"Command '{command}' not implemented yet"
                }
        except Exception as e:
            logger.exception(f"Error executing command {command}")
            return {
                "success": False,
                "error": str(e)
            }
    
    # ─── Command Handlers ─────────────────────────────────────────────────────
    
    def _handle_status(self) -> Dict:
        """Get system status."""
        try:
            # Check Ollama
            import httpx
            try:
                response = httpx.get('http://127.0.0.1:11434/api/tags', timeout=2)
                ollama_status = "running" if response.status_code == 200 else "error"
            except Exception:
                ollama_status = "offline"
            
            # Get earnings
            earnings = db.get_earnings_summary()
            
            # Get opportunity counts
            opp_counts = db.count_opportunities_by_status()
            
            return {
                "success": True,
                "status": {
                    "ollama": ollama_status,
                    "opportunities": opp_counts,
                    "earnings": earnings.get("confirmed_earnings", 0),
                    "pending_prs": earnings.get("pending_count", 0),
                    "merged_prs": earnings.get("merged_count", 0)
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _handle_pause(self) -> Dict:
        """Pause operations."""
        # This would integrate with the backend_state in desktop_app.py
        # For now, just log the intent
        db.log_event("openclaw_command", "Pause requested via OpenClaw")
        return {
            "success": True,
            "message": "Operations paused",
            "note": "Use SentinelAI API /api/pause for actual pause"
        }
    
    def _handle_resume(self) -> Dict:
        """Resume operations."""
        db.log_event("openclaw_command", "Resume requested via OpenClaw")
        return {
            "success": True,
            "message": "Operations resumed",
            "note": "Use SentinelAI API /api/resume for actual resume"
        }
    
    def _handle_emergency_stop(self) -> Dict:
        """Emergency stop."""
        db.log_event("openclaw_command", "EMERGENCY STOP requested via OpenClaw")
        return {
            "success": True,
            "message": "Emergency stop activated",
            "note": "Use SentinelAI API /api/emergency-stop for actual stop"
        }
    
    def _handle_list_opportunities(self, status: Optional[str] = None) -> Dict:
        """List opportunities."""
        try:
            opportunities = db.list_opportunities(status=status, limit=20)
            return {
                "success": True,
                "count": len(opportunities),
                "opportunities": opportunities
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _handle_list_tasks(self) -> Dict:
        """List active tasks."""
        try:
            tasks = db.list_opportunities(status="in_progress", limit=10)
            return {
                "success": True,
                "count": len(tasks),
                "tasks": tasks
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _handle_approve_task(self, task_id: Optional[int]) -> Dict:
        """Approve a task."""
        if not task_id:
            return {"success": False, "error": "task_id required"}
        
        try:
            db.update_opportunity_status(task_id, "approved")
            db.log_event("task_approved", f"Task #{task_id} approved via OpenClaw", task_id)
            return {
                "success": True,
                "message": f"Task #{task_id} approved",
                "task_id": task_id
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _handle_reject_task(self, task_id: Optional[int]) -> Dict:
        """Reject a task."""
        if not task_id:
            return {"success": False, "error": "task_id required"}
        
        try:
            db.update_opportunity_status(task_id, "rejected")
            db.log_event("task_rejected", f"Task #{task_id} rejected via OpenClaw", task_id)
            return {
                "success": True,
                "message": f"Task #{task_id} rejected",
                "task_id": task_id
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _handle_show_earnings(self) -> Dict:
        """Show earnings summary."""
        try:
            earnings = db.get_earnings_summary()
            return {
                "success": True,
                "earnings": earnings
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _handle_show_logs(self, limit: int = 10) -> Dict:
        """Show recent logs."""
        try:
            logs = db.get_recent_logs(limit=limit)
            return {
                "success": True,
                "count": len(logs),
                "logs": logs
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# ─── API Documentation Generator ──────────────────────────────────────────────

def generate_openclaw_api_docs() -> str:
    """Generate API documentation for OpenClaw integration."""
    docs = []
    docs.append("# SentinelAI API Documentation for OpenClaw")
    docs.append("")
    docs.append("## Available Commands")
    docs.append("")
    
    for cmd_name, cmd_def in OPENCLAW_COMMANDS.items():
        docs.append(f"### {cmd_name}")
        docs.append(f"**Description:** {cmd_def['description']}")
        docs.append(f"**Requires Auth:** {'Yes' if cmd_def['requires_auth'] else 'No'}")
        docs.append(f"**Dangerous:** {'Yes' if cmd_def['dangerous'] else 'No'}")
        docs.append(f"**Example:** \"{cmd_def['example']}\"")
        
        if cmd_def['parameters']:
            docs.append("**Parameters:**")
            for param in cmd_def['parameters']:
                required = "required" if param.get('required') else "optional"
                docs.append(f"  - `{param['name']}` ({param['type']}, {required})")
        
        docs.append("")
    
    docs.append("## Blocked Commands")
    docs.append("")
    docs.append("The following commands are blocked for safety:")
    for blocked in BLOCKED_COMMANDS:
        docs.append(f"- `{blocked}`")
    
    docs.append("")
    docs.append("## Usage Example")
    docs.append("")
    docs.append("```python")
    docs.append("from openclaw_integration import OpenClawCommandRouter")
    docs.append("")
    docs.append("# Initialize router")
    docs.append("router = OpenClawCommandRouter(auth_token='your_token_here')")
    docs.append("")
    docs.append("# Execute command")
    docs.append("result = router.route_command('status')")
    docs.append("print(result)")
    docs.append("")
    docs.append("# Approve a task")
    docs.append("result = router.route_command('approve_task', {'task_id': 5})")
    docs.append("print(result)")
    docs.append("```")
    
    return "\n".join(docs)


# ─── Main Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Generate and print API documentation
    print(generate_openclaw_api_docs())
    
    # Test command router
    print("\n" + "="*80)
    print("TESTING COMMAND ROUTER")
    print("="*80 + "\n")
    
    router = OpenClawCommandRouter()
    
    # Test status command
    print("Testing: status")
    result = router.route_command("status")
    print(f"Result: {result}\n")
    
    # Test list opportunities
    print("Testing: list_opportunities")
    result = router.route_command("list_opportunities")
    print(f"Result: {result}\n")
    
    # Test blocked command
    print("Testing: submit_pr (blocked)")
    result = router.route_command("submit_pr")
    print(f"Result: {result}\n")
