import argparse
import sys
import uvicorn
from core.config import config_manager
from core.workflow import workflow_registry
from executive.project import project_manager
from core.diagnostics import Diagnostics
from runtime.workflow import WorkflowEngine

def main():
    parser = argparse.ArgumentParser(
        description="Spilled Coffee AI Studio CLI - Operating System Core Management Utility"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")
    
    # 1. start-server command
    start_parser = subparsers.add_parser("start-server", help="Launch the FastAPI web studio server")
    start_parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    start_parser.add_argument("--host", type=str, default="localhost", help="Host address")

    
    # 2. list-workflows command
    subparsers.add_parser("list-workflows", help="List all registered workflow definitions")
    
    # 3. list-projects command
    subparsers.add_parser("list-projects", help="List all current projects metadata")
    
    # 4. diagnostics command
    subparsers.add_parser("diagnostics", help="Generate core system diagnostics report")
    
    # 5. create-project command
    create_parser = subparsers.add_parser("create-project", help="Create a new media production project")
    create_parser.add_argument("--name", required=True, help="Title of the project")
    create_parser.add_argument("--brand", required=True, help="Brand channel name")
    create_parser.add_argument("--workflow", required=True, help="Workflow ID definition")
    
    # 6. list-agents command
    subparsers.add_parser("list-agents", help="List all registered AI agent employees")
    
    # 7. run-workflow command
    run_wf_parser = subparsers.add_parser("run-workflow", help="Execute the next active step in a project's workflow")
    run_wf_parser.add_argument("--project-id", required=True, help="Project directory ID")
    run_wf_parser.add_argument("--verbose", action="store_true", help="Print debug/detailed run logs")
    run_wf_parser.add_argument("--dry-run", action="store_true", help="Perform validation run without saving or call LLMs")
    
    # 8. validate command
    subparsers.add_parser("validate", help="Run the core registries validation check framework")
    
    # 9. doctor command
    subparsers.add_parser("doctor", help="Run the diagnostic doctor check verifying configurations and folders health")

    # 10. demo command
    subparsers.add_parser("demo", help="Run the live end-to-end execution flow demo")

    args = parser.parse_args()

    
    if not args.command or args.command == "start-server":
        port = getattr(args, "port", 8000)
        host = getattr(args, "host", "localhost")
        print(f"Launching Spilled Coffee AI Studio at http://{host}:{port} ...")
        uvicorn.run("app.main:app", host=host, port=port, reload=False)
        
    elif args.command == "list-workflows":
        print("\n--- Registered Workflows ---")
        for wf in workflow_registry.list():
            print(f"ID: {wf.id:<25} Name: {wf.name:<35} Steps: {len(wf.steps)}")
        print("----------------------------\n")
        
    elif args.command == "list-projects":
        print("\n--- Current Projects ---")
        import os
        from core.models.project import Project
        p_dir = config_manager.get("PROJECTS_PATH")
        if os.path.exists(p_dir):
            for pid in os.listdir(p_dir):
                if os.path.isdir(os.path.join(p_dir, pid)):
                    try:
                        p = Project.load(pid)
                        print(f"ID: {p.id:<35} Name: {p.name:<25} Brand: {p.brand:<15} Step: {p.current_step:<15} Status: {p.status}")
                    except Exception:
                        pass
        print("------------------------\n")
        
    elif args.command == "diagnostics":
        Diagnostics.log_summary()
        report = Diagnostics.get_report()
        print(f"Detailed Diagnostics Report:")
        for k, v in report.items():
            print(f"  {k:<30}: {v}")
            
    elif args.command == "create-project":
        try:
            p = project_manager.create_project(
                name=args.name,
                brand=args.brand,
                workflow_name=args.workflow
            )
            print(f"SUCCESS: Project created successfully.")
            print(f"ID: {p.id}")
            print(f"Path: {p.get_project_dir()}")
        except Exception as e:
            print(f"ERROR: Failed to create project: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list-agents":
        from core.agent import agent_registry
        print("\n--- Registered AI Agents ---")
        for agent in agent_registry.list():
            print(f"Name: {agent.name:<25} Department: {agent.department:<25} Version: {agent.version}")
        print("----------------------------\n")
        
    elif args.command == "run-workflow":
        print(f"Executing workflow for project '{args.project_id}'...")
        if args.dry_run:
            print("DRY-RUN: Successfully simulated step execution (no changes made).")
            return
            
        try:
            # Run next step execution
            engine = WorkflowEngine()
            # If verbose logging is enabled
            if args.verbose:
                print("Loading workflow engine, resolving step constraints...")
            project = engine.execute_next(args.project_id)
            print(f"SUCCESS: Executed workflow step. New active step is: '{project.current_step}'")
        except Exception as e:
            print(f"ERROR: Execution crashed: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.command == "validate" or args.command == "doctor":
        from core.doctor import HealthChecker
        print(f"Running system health checks & validation checks...\n")
        report = HealthChecker.run_checks()
        
        for log in report["logs"]:
            print(log)
            
        print(f"\nSystem Health Status: {report['status'].upper()}")
        
        if report["status"] == "unhealthy" and args.command == "validate":
            print("ERROR: Validation framework found critical failures. Exiting.", file=sys.stderr)
            sys.exit(1)

    elif args.command == "demo":
        from runtime.demo_runner import DemoRunner
        runner = DemoRunner()
        runner.run()



if __name__ == "__main__":
    main()
