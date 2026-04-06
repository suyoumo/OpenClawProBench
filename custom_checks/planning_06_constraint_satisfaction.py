"""Planning 06: 约束满足问题 — 会议调度优化 — 评分脚本

检查模型是否：
1. 所有会议都被安排
2. 满足所有硬约束
3. 满足时间约束
4. 满足会议室约束
"""

from pathlib import Path
import json


def grade(workspace: str, trace: dict) -> dict:
    """评分函数"""
    workspace_path = Path(workspace)
    checkpoints = {}
    
    # 1. 检查文件是否存在
    schedule_file = workspace_path / "schedule.json"
    
    if not schedule_file.exists():
        return {
            "checkpoints": {
                "file_exists": {
                    "score": 0.0,
                    "max": 1.0,
                    "detail": "schedule.json not created",
                }
            }
        }
    
    # 读取调度方案
    try:
        with open(schedule_file) as f:
            schedule = json.load(f)
    except Exception as e:
        return {
            "checkpoints": {
                "file_exists": {
                    "score": 0.0,
                    "max": 1.0,
                    "detail": f"schedule.json parse error: {e}",
                }
            }
        }
    
    # 2. 检查是否安排了所有 5 个会议
    required_meetings = {
        "Product Review",
        "Tech Design",
        "Budget Planning",
        "Team Sync",
        "Client Demo",
    }
    
    scheduled_meetings = set()

    if isinstance(schedule, list):
        for meeting in schedule:
            # Try multiple common key names for meeting name
            name = (meeting.get("name") or meeting.get("meeting") or
                    meeting.get("title") or meeting.get("meeting_name") or "")
            if name:
                scheduled_meetings.add(name)
    elif isinstance(schedule, dict):
        # Could be keyed by meeting name directly, or have a "meetings" sub-key
        if "meetings" in schedule and isinstance(schedule["meetings"], list):
            for meeting in schedule["meetings"]:
                name = (meeting.get("name") or meeting.get("meeting") or
                        meeting.get("title") or meeting.get("meeting_name") or "")
                if name:
                    scheduled_meetings.add(name)
        else:
            for name in schedule.keys():
                scheduled_meetings.add(name)
    
    meeting_coverage = len(scheduled_meetings & required_meetings) / len(required_meetings)
    
    checkpoints["all_meetings_scheduled"] = {
        "score": meeting_coverage * 0.2,
        "max": 0.2,
        "detail": f"Scheduled {len(scheduled_meetings & required_meetings)}/5 meetings",
    }
    
    # 3. 检查时间约束
    # Alice 必须在 14:00 后参加 Product Review
    # Bob 在 11:00-14:00 不可用
    # Eve 必须在 12:00 前参加 Client Demo
    
    time_constraints_satisfied = True
    constraint_details = []
    
    if isinstance(schedule, list):
        for meeting in schedule:
            name = meeting.get("name", meeting.get("meeting", ""))
            start_time = meeting.get("start_time", meeting.get("start", ""))
            
            # 提取小时
            try:
                hour = int(start_time.split(":")[0])
                
                if name == "Product Review" and "Alice" in str(meeting.get("attendees", [])):
                    if hour < 14:
                        time_constraints_satisfied = False
                        constraint_details.append(f"Alice in Product Review at {start_time} (< 14:00)")
                
                if name == "Tech Design" and "Bob" in str(meeting.get("attendees", [])):
                    if 11 <= hour < 14:
                        time_constraints_satisfied = False
                        constraint_details.append(f"Bob in Tech Design at {start_time} (11:00-14:00)")
                
                if name == "Client Demo" and "Eve" in str(meeting.get("attendees", [])):
                    if hour >= 12:
                        time_constraints_satisfied = False
                        constraint_details.append(f"Eve in Client Demo at {start_time} (>= 12:00)")
                        
            except:
                pass
    
    if time_constraints_satisfied:
        checkpoints["time_constraints"] = {
            "score": 0.25,
            "max": 0.25,
            "detail": "All time constraints satisfied ✅",
        }
    else:
        checkpoints["time_constraints"] = {
            "score": 0.0,
            "max": 0.25,
            "detail": f"Time constraints violated: {'; '.join(constraint_details[:3])}",
        }
    
    # 4. 检查会议室约束（最多 2 个会议室同时使用）
    room_constraint_satisfied = True
    room_violations = []
    
    if isinstance(schedule, list):
        # 按时间排序
        time_slots = {}
        for meeting in schedule:
            start = meeting.get("start_time", meeting.get("start", "00:00"))
            end = meeting.get("end_time", meeting.get("end", "01:00"))
            
            try:
                start_hour = int(start.split(":")[0])
                end_hour = int(end.split(":")[0])
                
                for hour in range(start_hour, end_hour):
                    if hour not in time_slots:
                        time_slots[hour] = []
                    time_slots[hour].append(meeting.get("room", "A"))
            except:
                pass
        
        for hour, rooms in time_slots.items():
            unique_rooms = set(rooms)
            if len(unique_rooms) > 2:
                room_constraint_satisfied = False
                room_violations.append(f"{hour}:00 has {len(unique_rooms)} meetings")
    
    if room_constraint_satisfied:
        checkpoints["room_constraints"] = {
            "score": 0.25,
            "max": 0.25,
            "detail": "Room constraints satisfied (≤2 concurrent) ✅",
        }
    else:
        checkpoints["room_constraints"] = {
            "score": 0.0,
            "max": 0.25,
            "detail": f"Room constraints violated: {'; '.join(room_violations[:3])}",
        }
    
    # 5. 检查依赖约束（Budget Planning 必须在 Tech Design 之前）
    dependency_satisfied = True
    
    if isinstance(schedule, list):
        budget_time = None
        tech_time = None
        
        for meeting in schedule:
            name = meeting.get("name", meeting.get("meeting", ""))
            start_time = meeting.get("start_time", meeting.get("start", ""))
            
            try:
                hour = int(start_time.split(":")[0])
                
                if name == "Budget Planning":
                    budget_time = hour
                elif name == "Tech Design":
                    tech_time = hour
            except:
                pass
        
        if budget_time and tech_time:
            if budget_time >= tech_time:
                dependency_satisfied = False
    
    if dependency_satisfied:
        checkpoints["dependency_constraints"] = {
            "score": 0.15,
            "max": 0.15,
            "detail": "Dependency constraints satisfied ✅",
        }
    else:
        checkpoints["dependency_constraints"] = {
            "score": 0.0,
            "max": 0.15,
            "detail": "Budget Planning should be before Tech Design",
        }
    
    # 6. 检查参会人员冲突（同一时间同一人不能在两个会议）
    attendee_conflict = False
    conflict_details = []
    
    if isinstance(schedule, list):
        time_attendees = {}
        
        for meeting in schedule:
            start = meeting.get("start_time", meeting.get("start", "00:00"))
            end = meeting.get("end_time", meeting.get("end", "01:00"))
            attendees = meeting.get("attendees", [])
            
            try:
                start_hour = int(start.split(":")[0])
                end_hour = int(end.split(":")[0])
                
                for hour in range(start_hour, end_hour):
                    if hour not in time_attendees:
                        time_attendees[hour] = []
                    
                    for attendee in attendees:
                        if attendee in time_attendees[hour]:
                            attendee_conflict = True
                            conflict_details.append(f"{attendee} at {hour}:00")
                        else:
                            time_attendees[hour].append(attendee)
            except:
                pass
    
    if not attendee_conflict:
        checkpoints["attendee_constraints"] = {
            "score": 0.15,
            "max": 0.15,
            "detail": "No attendee conflicts ✅",
        }
    else:
        checkpoints["attendee_constraints"] = {
            "score": 0.0,
            "max": 0.15,
            "detail": f"Attendee conflicts: {'; '.join(conflict_details[:3])}",
        }
    
    return {"checkpoints": checkpoints}


def grade_process(trace: dict) -> float:
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        if e.get("tool") in ("write", "Write"):
            path = str((e.get("args") or {}).get("path", "") or (e.get("args") or {}).get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    return 1.0 if wrote_json else 0.3
