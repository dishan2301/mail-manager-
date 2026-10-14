from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from fastapi import Request
from fastapi.testclient import TestClient
from app.api import routes
from app.core.database import SessionLocal
from app.main import app
from app.models.entities import Classification,Email,EmailStatus,Employee,SLATier

def auth(client):
    response=client.post("/api/auth/login",data={"username":"admin@oeis.local","password":"OEIS-Admin@July2026#47"});return {"Authorization":f"Bearer {response.json()['access_token']}"}
def test_mailbox_employee_pending_assignment_and_report_workflow():
    with TestClient(app) as client:
        headers=auth(client)
        mailbox=client.post("/api/mailboxes",headers=headers,json={"address":"workflow@example.com","display_name":"Workflow mailbox","timezone":"Asia/Kolkata"});assert mailbox.status_code==201
        employee=client.post("/api/employees",headers=headers,json={"name":"Test Employee","email":"employee@example.com","active":True});assert employee.status_code==201
        with SessionLocal() as db:
            row=Email(mailbox_id=mailbox.json()["id"],message_id="workflow-message",conversation_id="conversation",internet_message_id="<workflow@example.com>",sender="customer@example.com",receiver="workflow@example.com",subject="Workflow customer request",received_time=datetime.now(timezone.utc),folder="inbox",categories=[],classification=Classification.CUSTOMER,status=EmailStatus.PENDING,pending_hours=9,sla_tier=SLATier.OVERDUE);db.add(row);db.commit();db.refresh(row);email_id=row.id
        pending=client.get("/api/emails/pending?search=Workflow&status=overdue",headers=headers);assert pending.status_code==200 and pending.json()["total"]==1
        assigned=client.patch(f"/api/emails/{email_id}/assignment?employee_id={employee.json()['id']}",headers=headers);assert assigned.status_code==200
        assert client.get("/api/emails/pending?search=Test%20Employee",headers=headers).json()["total"]==1
        assert client.get("/api/emails/pending?search=workflow@example.com",headers=headers).json()["total"]==1
        performance=client.get("/api/employees/performance",headers=headers);assert performance.status_code==200 and performance.json()[0]["pending"]==1
        report=client.get("/api/reports/daily?dimension=mailbox",headers=headers);assert report.status_code==200
        row=next(row for row in report.json()["rows"] if row["dimension"]=="workflow@example.com")
        assert row["not_replied"]==1 and row["total_received"]==1 and row["reply_rate"]==0

def test_pending_queue_is_prioritized_and_numbered_across_pages():
    with TestClient(app) as client:
        headers=auth(client)
        mailbox=client.post("/api/mailboxes",headers=headers,json={"address":"queue-order@example.com","display_name":"Queue order","timezone":"Asia/Kolkata"})
        assert mailbox.status_code==201
        now=datetime.now(timezone.utc)
        fixtures=[
            ("warning","Queue ordering warning",100,SLATier.WARNING),
            ("critical-newer","Queue ordering critical newer",50,SLATier.CRITICAL),
            ("critical-older","Queue ordering critical older",70,SLATier.CRITICAL),
            ("overdue","Queue ordering overdue",200,SLATier.OVERDUE),
        ]
        with SessionLocal() as db:
            for index,(message_id,subject,hours,tier) in enumerate(fixtures):
                db.add(Email(mailbox_id=mailbox.json()["id"],message_id=message_id,conversation_id=message_id,internet_message_id=f"<{message_id}@example.com>",sender="queue-customer@example.com",receiver="queue-order@example.com",subject=subject,received_time=now-timedelta(hours=hours,seconds=index),folder="inbox",categories=[],classification=Classification.CUSTOMER,status=EmailStatus.PENDING,pending_hours=hours,sla_tier=tier))
            db.commit()
        first=client.get("/api/emails/pending?page=1&page_size=2&search=Queue%20ordering",headers=headers).json()
        second=client.get("/api/emails/pending?page=2&page_size=2&search=Queue%20ordering",headers=headers).json()
        assert [row["serial_number"] for row in first["items"]]==[1,2]
        assert [row["serial_number"] for row in second["items"]]==[3,4]
        assert [row["subject"] for row in first["items"]+second["items"]]==[
            "Queue ordering critical older",
            "Queue ordering critical newer",
            "Queue ordering overdue",
            "Queue ordering warning",
        ]

def test_admin_assignment_route_sets_selected_employee_and_audits():
    email=SimpleNamespace(id=7,assigned_employee_id=None);employee=SimpleNamespace(id=3)
    class DB:
        def __init__(self):self.events=[];self.commits=0
        def get(self,model,key):
            if model is Email and key==7:return email
            if model is Employee and key==3:return employee
        def add(self,row):self.events.append(row)
        def commit(self):self.commits+=1
    db=DB();request=Request({"type":"http","method":"PATCH","path":"/api/emails/7/assignment","headers":[],"client":("127.0.0.1",1)})
    result=routes.assign_email(7,request,3,{"user_id":1,"role":"admin"},db)
    assert result=={"id":7,"assigned_employee_id":3} and email.assigned_employee_id==3
    assert db.commits==1 and db.events[-1].action=="email.assignment.update"
