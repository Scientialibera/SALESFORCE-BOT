#!/usr/bin/env python3
"""Script to fix plan.plan_id references to plan.id"""

import os
import re

def fix_plan_id_references(file_path):
    """Fix plan.plan_id references to plan.id"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Pattern to match plan.plan_id references
        pattern = r'plan\.plan_id'
        
        # Replace with plan.id
        new_content = re.sub(pattern, 'plan.id', content)
        
        # Check if any changes were made
        if content != new_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Fixed {file_path}")
            return True
        else:
            print(f"No changes needed in {file_path}")
            return False
            
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def main():
    """Fix all repository and service files"""
    base_path = r'c:\Users\emili\Documents\SALESFORCE-BOT\chatbot\src\chatbot'
    
    # Files to fix
    files_to_fix = [
        'services/planner_service.py'
    ]
    
    fixed_count = 0
    
    for file_path in files_to_fix:
        full_path = os.path.join(base_path, file_path)
        if os.path.exists(full_path):
            if fix_plan_id_references(full_path):
                fixed_count += 1
        else:
            print(f"File not found: {full_path}")
    
    print(f"\nFixed {fixed_count} files")

if __name__ == '__main__':
    main()