import os
from rope.base.project import Project
from rope.refactor.rename import Rename
from rope.refactor.occurrences import Occurrences

def rename_in_project(project_root, old_name, new_name):
    project = Project(project_root)
    
    # Find all occurrences of the old name
    finder = Occurrences(project, old_name)
    occurrences = finder.all_occurrences()

    if not occurrences:
        print(f"No occurrences of '{old_name}' found in the project.")
        return

    # Group occurrences by resource (file)
    occurrences_by_resource = {}
    for occurrence in occurrences:
        resource = occurrence.resource
        if resource not in occurrences_by_resource:
            occurrences_by_resource[resource] = []
        occurrences_by_resource[resource].append(occurrence)

    # Perform renaming for each resource
    for resource, resource_occurrences in occurrences_by_resource.items():
        print(f"Renaming in {resource.path}...")
        
        # Create a Rename refactoring for this resource
        renamer = Rename(project, resource, old_name)
        changes = renamer.get_changes(new_name)
        
        # Apply the changes
        project.do(changes)

    print("Renaming complete.")

# Use the current directory as the project root
project_root = '.'
old_name = 'OpenAIFunction'
new_name = 'FunctionTool'

rename_in_project(project_root, old_name, new_name)
