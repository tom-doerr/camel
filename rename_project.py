import os
from rope.base.project import Project
from rope.refactor.rename import Rename

def rename_in_project(project_root, old_name, new_name):
    project = Project(project_root)
    
    # Find all Python files in the project
    resources = [r for r in project.get_files() if r.name.endswith('.py')]

    for resource in resources:
        print(f"Checking {resource.path}...")
        
        # Create a Rename refactoring for this resource
        renamer = Rename(project, resource, old_name)
        changes = renamer.get_changes(new_name)
        
        # Apply the changes if any were found
        if changes.changes:
            print(f"Renaming in {resource.path}...")
            project.do(changes)

    print("Renaming complete.")

# Use the current directory as the project root
project_root = '.'
old_name = 'OpenAIFunction'
new_name = 'FunctionTool'

rename_in_project(project_root, old_name, new_name)
