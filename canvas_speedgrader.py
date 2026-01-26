#!/usr/bin/env python3
"""
Canvas Speed Grader - Local Canvas API Interface

A standalone Python program that acts as a local speed grader interface:
1. Reads discussion submissions from Canvas
2. Reads course roster (including Login IDs) 
3. Calls external grading executable for each submission
4. Posts grades and comments back to Canvas

This script handles ONLY Canvas API interactions - all grading logic is external.

Requirements:
- Python 3.6+
- requests library (pip install requests)
- Canvas API developer key
- External grading executable

Usage:
    python canvas_speedgrader.py --course-id 12345 --discussion-id 67890 --grader ./my_grader.py
"""

import requests
import json
import argparse
import logging
import sys
import subprocess
import os
from typing import Dict, List, Optional, Any
from datetime import datetime


class CanvasAPIClient:
    """Client for interacting with Canvas API"""
    
    def __init__(self, base_url: str, api_key: str):
        """
        Initialize the Canvas API client
        
        Args:
            base_url: Canvas instance URL (e.g., 'https://canvas.instructure.com')
            api_key: Canvas API developer key
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('canvas_speedgrader.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """
        Make an API request to Canvas
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for requests
            
        Returns:
            JSON response or list for paginated responses
            
        Raises:
            requests.RequestException: If the request fails
        """
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"API request failed: {method} {url} - {str(e)}")
            raise
    
    def _get_paginated(self, endpoint: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Get all pages of a paginated API endpoint
        
        Args:
            endpoint: API endpoint
            **kwargs: Additional arguments for requests
            
        Returns:
            List of all items across all pages
        """
        items = []
        page = 1
        per_page = 100
        
        while True:
            params = kwargs.get('params', {})
            params.update({'page': page, 'per_page': per_page})
            kwargs['params'] = params
            
            response = self._make_request('GET', endpoint, **kwargs)
            
            if not response:
                break
                
            items.extend(response)
            
            if len(response) < per_page:
                break
                
            page += 1
        
        return items
    
    def get_students(self, course_id: int) -> List[Dict[str, Any]]:
        """
        Get students in a course
        
        Args:
            course_id: Canvas course ID
            
        Returns:
            List of students with their data
        """
        self.logger.info(f"Fetching students for course {course_id}")
        endpoint = f"courses/{course_id}/users"
        
        students = self._get_paginated(endpoint, params={'enrollment_type[]': ['student'], 'include[]': ['email', 'login_id']})
        self.logger.info(f"Retrieved {len(students)} students")
        return students
    
    def get_discussion(self, course_id: int, discussion_id: int) -> Dict[str, Any]:
        """
        Get discussion topic details
        
        Args:
            course_id: Canvas course ID
            discussion_id: Canvas discussion topic ID
            
        Returns:
            Discussion topic data
        """
        self.logger.info(f"Fetching discussion {discussion_id} from course {course_id}")
        endpoint = f"courses/{course_id}/discussion_topics/{discussion_id}"
        return self._make_request('GET', endpoint)
    
    def get_discussion_entries(self, course_id: int, discussion_id: int) -> List[Dict[str, Any]]:
        """
        Get all entries (posts) in a discussion
        
        Args:
            course_id: Canvas course ID
            discussion_id: Canvas discussion topic ID
            
        Returns:
            List of discussion entries
        """
        self.logger.info(f"Fetching discussion entries for discussion {discussion_id}")
        endpoint = f"courses/{course_id}/discussion_topics/{discussion_id}/entries"
        
        entries = self._get_paginated(endpoint)
        self.logger.info(f"Retrieved {len(entries)} discussion entries")
        return entries
    
    def post_discussion_reply(self, course_id: int, discussion_id: int, 
                            message: str, parent_id: int) -> Dict[str, Any]:
        """
        Post a reply to a discussion entry
        
        Args:
            course_id: Canvas course ID
            discussion_id: Canvas discussion topic ID
            message: Reply message text
            parent_id: ID of parent entry to reply to
            
        Returns:
            Created entry data
        """
        endpoint = f"courses/{course_id}/discussion_topics/{discussion_id}/entries"
        
        data = {
            'message': message,
            'parent_id': parent_id
        }
        
        self.logger.info(f"Posting reply to entry {parent_id} in discussion {discussion_id}")
        return self._make_request('POST', endpoint, json=data)
    
    def submit_grade(self, course_id: int, assignment_id: int, 
                    user_id: int, grade: str, comment: Optional[str] = None) -> Dict[str, Any]:
        """
        Submit a grade for an assignment (including graded discussions)
        
        Args:
            course_id: Canvas course ID
            assignment_id: Canvas assignment ID
            user_id: Canvas user ID to grade
            grade: Grade value (points or letter grade)
            comment: Optional comment for the grade
            
        Returns:
            Submission data
        """
        endpoint = f"courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}"
        
        data = {
            'submission': {
                'posted_grade': grade
            }
        }
        
        if comment:
            data['comment'] = {
                'text_comment': comment
            }
        
        self.logger.info(f"Submitting grade for user {user_id}: {grade}")
        return self._make_request('PUT', endpoint, json=data)


class LocalSpeedGrader:
    """Local Speed Grader - orchestrates grading workflow"""
    
    def __init__(self, canvas_client: CanvasAPIClient, grader_executable: str):
        """
        Initialize the local speed grader
        
        Args:
            canvas_client: Canvas API client instance
            grader_executable: Path to external grading executable
        """
        self.canvas = canvas_client
        self.grader_executable = grader_executable
        self.logger = logging.getLogger(__name__)
        
        # Verify grader executable exists and is executable
        if not os.path.exists(grader_executable):
            raise FileNotFoundError(f"Grader executable not found: {grader_executable}")
        if not os.access(grader_executable, os.X_OK):
            raise PermissionError(f"Grader executable is not executable: {grader_executable}")
    
    def get_student_roster(self, course_id: int) -> Dict[int, Dict[str, Any]]:
        """
        Get student roster with login IDs
        
        Args:
            course_id: Canvas course ID
            
        Returns:
            Dictionary mapping user_id to user info (including login_id)
        """
        students = self.canvas.get_students(course_id)
        roster = {}
        
        for student in students:
            roster[student['id']] = {
                'user_id': student['id'],
                'name': student['name'],
                'login_id': student.get('login_id', 'unknown'),
                'email': student.get('email', ''),
                'sortable_name': student.get('sortable_name', student['name'])
            }
        
        self.logger.info(f"Found {len(roster)} students in roster")
        return roster
    
    def call_grader(self, submission_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call external grading executable with submission data
        
        Args:
            submission_data: Complete submission information
            
        Returns:
            Grading result with grade and comment
            
        Raises:
            subprocess.CalledProcessError: If grader executable fails
            json.JSONDecodeError: If grader output is not valid JSON
        """
        try:
            # Convert submission data to JSON for the grader
            input_json = json.dumps(submission_data, indent=2)
            
            # Call the external grader
            result = subprocess.run(
                [self.grader_executable],
                input=input_json,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            if result.returncode != 0:
                self.logger.error(f"Grader executable failed with return code {result.returncode}")
                self.logger.error(f"Stderr: {result.stderr}")
                raise subprocess.CalledProcessError(result.returncode, self.grader_executable)
            
            # Parse the grader's JSON output
            grading_result = json.loads(result.stdout.strip())
            
            # Validate required fields
            if 'grade' not in grading_result:
                raise ValueError("Grader output missing required 'grade' field")
            
            return grading_result
            
        except subprocess.TimeoutExpired:
            self.logger.error("Grader executable timed out")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON from grader: {e}")
            self.logger.error(f"Grader output: {result.stdout}")
            raise
    
    def process_discussion(self, course_id: int, discussion_id: int, 
                         assignment_id: Optional[int] = None,
                         dry_run: bool = True,
                         only_student: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Process all submissions in a discussion
        
        Args:
            course_id: Canvas course ID
            discussion_id: Canvas discussion topic ID
            assignment_id: Assignment ID (required for grading)
            dry_run: If True, don't actually post grades/comments
            
        Returns:
            List of processing results
        """
        # Get discussion info
        discussion = self.canvas.get_discussion(course_id, discussion_id)
        
        # Get student roster
        roster = self.get_student_roster(course_id)
        
        # Filter roster to only specified student if requested
        if only_student:
            filtered_roster = {}
            target_student = None
            for user_id, student_info in roster.items():
                if student_info['login_id'] == only_student:
                    filtered_roster[user_id] = student_info
                    target_student = student_info
                    break
            
            if not target_student:
                self.logger.error(f"Student with login_id '{only_student}' not found in course roster")
                return []
            
            self.logger.info(f"SINGLE STUDENT MODE: Only processing {target_student['login_id']} ({target_student['name']})")
            roster = filtered_roster
        
        # Get discussion entries
        entries = self.canvas.get_discussion_entries(course_id, discussion_id)
        
        # Filter to student submissions (not instructor posts)
        student_entries = [
            entry for entry in entries 
            if entry.get('user_id') in roster
        ]
        
        # Identify students with submissions
        students_with_submissions = set(entry.get('user_id') for entry in student_entries)
        
        # Identify students without submissions
        students_without_submissions = []
        for user_id, student_info in roster.items():
            if user_id not in students_with_submissions:
                students_without_submissions.append(student_info)
        
        self.logger.info(f"Found {len(students_with_submissions)} students with submissions")
        self.logger.info(f"Found {len(students_without_submissions)} students without submissions")
        
        # Report students without submissions
        if students_without_submissions:
            self.logger.info("Students without submissions:")
            for student in students_without_submissions:
                self.logger.info(f"  - {student['login_id']} ({student['name']})")
        
        self.logger.info(f"Processing {len(student_entries)} student submissions")
        results = []
        
        # Add entries for students without submissions (no grading needed)
        for student in students_without_submissions:
            results.append({
                'user_id': student['user_id'],
                'login_id': student['login_id'],
                'student_name': student['name'],
                'entry_id': None,
                'grade': None,
                'comment': None,
                'status': 'NO_SUBMISSION',
                'dry_run': dry_run
            })
        
        # Process students with submissions
        for entry in student_entries:
            user_id = entry['user_id']
            student_info = roster[user_id]
            
            try:
                # Prepare submission data for grader
                submission_data = {
                    'discussion': {
                        'id': discussion_id,
                        'title': discussion.get('title', ''),
                        'prompt': discussion.get('message', '')
                    },
                    'student': student_info,
                    'submission': {
                        'entry_id': entry['id'],
                        'message': entry['message'],
                        'created_at': entry.get('created_at'),
                        'updated_at': entry.get('updated_at'),
                        'word_count': len(entry['message'].split())
                    }
                }
                
                # Call external grader
                self.logger.info(f"Grading submission from {student_info['login_id']} ({student_info['name']})")
                grading_result = self.call_grader(submission_data)
                
                # Prepare result record
                result = {
                    'user_id': user_id,
                    'login_id': student_info['login_id'],
                    'student_name': student_info['name'],
                    'entry_id': entry['id'],
                    'grade': grading_result['grade'],
                    'comment': grading_result.get('comment', ''),
                    'grader_output': grading_result,
                    'dry_run': dry_run
                }
                
                # Post grade if not dry run and assignment_id provided
                if not dry_run and assignment_id:
                    try:
                        self.canvas.submit_grade(
                            course_id, assignment_id, user_id,
                            grading_result['grade'],
                            grading_result.get('comment')
                        )
                        result['grade_posted'] = True
                    except Exception as e:
                        self.logger.error(f"Failed to post grade for {student_info['login_id']}: {e}")
                        result['grade_posted'] = False
                        result['grade_error'] = str(e)
                
                # Note: Discussion replies removed for privacy - comments go through grade submission only
                
                results.append(result)
                
            except Exception as e:
                self.logger.error(f"Failed to process submission from {student_info['login_id']}: {e}")
                results.append({
                    'user_id': user_id,
                    'login_id': student_info['login_id'],
                    'student_name': student_info['name'],
                    'entry_id': entry['id'],
                    'error': str(e),
                    'dry_run': dry_run
                })
        
        return results


def load_config():
    """Load configuration from environment variables or config file"""
    config = {
        'canvas_url': os.getenv('CANVAS_URL'),
        'api_key': os.getenv('CANVAS_API_KEY')
    }
    
    # Try to load from config file if environment variables not set
    try:
        if os.path.exists('canvas_config.json'):
            with open('canvas_config.json', 'r') as f:
                file_config = json.load(f)
                for key in config:
                    if config[key] is None and key in file_config:
                        config[key] = file_config[key]
    except Exception as e:
        logging.warning(f"Could not load config file: {e}")
    
    return config


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Canvas Local Speed Grader')
    parser.add_argument('--course-id', type=int, required=True, help='Canvas course ID')
    parser.add_argument('--discussion-id', type=int, required=True, help='Canvas discussion topic ID')
    parser.add_argument('--assignment-id', type=int, help='Assignment ID (required for posting grades)')
    parser.add_argument('--grader', required=True, help='Path to external grading executable')
    parser.add_argument('--live', action='store_true', help='Actually post grades/comments (default is dry run)')
    parser.add_argument('--canvas-url', help='Canvas instance URL')
    parser.add_argument('--api-key', help='Canvas API key')
    parser.add_argument('--output', help='Output file for results (JSON format)')
    parser.add_argument('--only-student', help='Only process this student (by login_id) - useful for testing')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config()
    canvas_url = args.canvas_url or config['canvas_url']
    api_key = args.api_key or config['api_key']
    
    if not canvas_url or not api_key:
        print("Error: Canvas URL and API key are required")
        print("Set them via --canvas-url and --api-key arguments, or")
        print("Set CANVAS_URL and CANVAS_API_KEY environment variables, or")
        print("Create a canvas_config.json file with these values")
        sys.exit(1)
    
    try:
        # Initialize Canvas client
        canvas_client = CanvasAPIClient(canvas_url, api_key)
        
        # Initialize speed grader
        speed_grader = LocalSpeedGrader(canvas_client, args.grader)
        
        # Process the discussion
        dry_run = not args.live
        if dry_run:
            print("=== DRY RUN MODE ===")
            print("Use --live flag to actually post grades and comments")
        
        print(f"Processing discussion {args.discussion_id} in course {args.course_id}")
        if args.only_student:
            print(f"SINGLE STUDENT MODE: Only processing student '{args.only_student}'")
        results = speed_grader.process_discussion(
            args.course_id, args.discussion_id,
            assignment_id=args.assignment_id,
            dry_run=dry_run,
            only_student=args.only_student
        )
        
        # Display results
        students_with_submissions = [r for r in results if r.get('status') != 'NO_SUBMISSION']
        students_without_submissions = [r for r in results if r.get('status') == 'NO_SUBMISSION']
        
        print(f"\nProcessed {len(results)} total students:")
        print(f"  - {len(students_with_submissions)} students with submissions (graded)")
        print(f"  - {len(students_without_submissions)} students without submissions (skipped)")
        
        if students_with_submissions:
            print(f"\nStudents with submissions:")
            for result in students_with_submissions:
                if 'error' in result:
                    print(f"ERROR - {result['login_id']} ({result['student_name']}): {result['error']}")
                else:
                    status = ""
                    if not dry_run:
                        if result.get('grade_posted'):
                            status += "✓ Grade & private comment posted "
                    print(f"{result['login_id']} ({result['student_name']}): Grade={result['grade']} {status}")
        
        if students_without_submissions:
            print(f"\nStudents without submissions (skipped grading):")
            for result in students_without_submissions:
                print(f"{result['login_id']} ({result['student_name']}): NO SUBMISSION")
        
        # Save results to file if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"Results saved to {args.output}")
        
        print("Processing complete!")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
