#!/usr/bin/env python3
"""Script to remove enable_cross_partition_query parameters from all repository files"""

import os
import re

def fix_cosmos_params(file_path):
    """Remove enable_cross_partition_query parameters from a file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Pattern to match enable_cross_partition_query parameter
        pattern = r',\s*enable_cross_partition_query=True'
        
        # Remove the parameter
        new_content = re.sub(pattern, '', content)
        
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
        'repositories/cache_repository.py',
        'repositories/feedback_repository.py', 
        'repositories/sql_schema_repository.py',
        'services/telemetry_service.py',
        'services/retrieval_service.py'
    ]
    
    fixed_count = 0
    
    for file_path in files_to_fix:
        full_path = os.path.join(base_path, file_path)
        if os.path.exists(full_path):
            if fix_cosmos_params(full_path):
                fixed_count += 1
        else:
            print(f"File not found: {full_path}")
    
    print(f"\nFixed {fixed_count} files")

if __name__ == '__main__':
    main()