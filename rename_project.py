import os
from rope.base.project import Project
from rope.refactor.rename import Rename
from rope.base.libutils import path_to_resource

def rename_in_project(project_root, old_name, new_name):
    project = Project(project_root)
    
    # Find all Python files in the project
    resources = [r for r in project.get_files() if r.name.endswith('.py')]

    for resource in resources:
        print(f"Checking {resource.path}...")
        
        # Read the content of the file
        with open(resource.real_path, 'r') as file:
            content = file.read()
        
        # Check if the old_name exists in the file
        if old_name in content:
            # Create a Rename refactoring for this resource
            renamer = Rename(project, resource, old_name)
            
            # Find the occurrences of old_name
            occurrences = renamer.get_occurrences()
            
            if occurrences:
                print(f"Renaming in {resource.path}...")
                changes = renamer.get_changes(new_name)
                project.do(changes)

    print("Renaming complete.")

# Use the current directory as the project root
project_root = '.'
old_name = 'OpenAIFunction'
new_name = 'FunctionTool'

rename_in_project(project_root, old_name, new_name)
