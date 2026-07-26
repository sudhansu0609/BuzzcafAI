import os
import logging
from executive.project import project_manager
from runtime.workflow import WorkflowEngine

logger = logging.getLogger("spilled_coffee_ai.runtime.demo_runner")

class DemoRunner:
    def run(self):
        print("="*60)
        print("Starting Live Spilled Coffee AI End-to-End Demo")
        print("="*60)

        print("1. Creating project using ProjectManager...")
        project_name = "The Last Lantern"
        brand_name = "Khayal3Baje"
        workflow_id = "khayal3baje_horror"
        
        try:
            project = project_manager.create_project(
                name=project_name,
                brand=brand_name,
                workflow_name=workflow_id
            )
            print(f"   Project created successfully. ID: {project.id}")
            print(f"   Saved at: {project.get_project_dir()}")
            
            engine = WorkflowEngine()
            
            print("\n2. Running research phase...")
            project = engine.execute_next(project.id)
            print(f"   Completed. New Active Step: {project.current_step}")
            
            print("\n3. Writing script phase...")
            project = engine.execute_next(project.id)
            print(f"   Completed. New Active Step: {project.current_step}")
            
            print("\n4. Preparing production assets...")
            project = engine.execute_next(project.id)
            print(f"   Completed. New Active Step: {project.current_step}")
            
            print("\n5. Preparing publishing metadata package...")
            project = engine.execute_next(project.id)
            print(f"   Completed. New Active Step: {project.current_step}")
            
            print("\n6. Collecting post-publish analytics...")
            project = engine.execute_next(project.id)
            print(f"   Completed. New Active Step: {project.current_step}")
            
            print("\n" + "="*60)
            print("Demo completed successfully. Live project state: COMPLETED")
            print("="*60)
            
        except Exception as e:
            print(f"\nERROR: Demo run crashed: {e}")
            logger.error(f"DemoRunner crash: {e}", exc_info=True)
