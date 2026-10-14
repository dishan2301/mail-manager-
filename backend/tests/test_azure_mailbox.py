from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.core.database import Base, get_db
from app.models.entities import Mailbox
from app.services.secrets import mailbox_graph_settings


def test_mailbox_submit_saves_encrypted_azure_credentials():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    app=FastAPI();app.include_router(routes.router)
    def database():
        with sessions() as db:yield db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[routes.admin.dependency]=lambda:{"user_id":1,"role":"admin"}
    with TestClient(app) as client:
        invalid=client.post("/api/mailboxes",json={"address":"incomplete@example.com","display_name":"Incomplete","provider":"microsoft","azure_client_id":"client-id"})
        assert invalid.status_code==422
        response=client.post("/api/mailboxes",json={"address":"owner@example.com","display_name":"Owner","provider":"microsoft","azure_client_id":"client-id","azure_tenant_id":"tenant-id","azure_client_secret":"super-secret"})
        assert response.status_code==201,response.text
        body=response.json()
        assert body["azure_client_id"]=="client-id" and body["azure_secret_saved"] is True
        assert "super-secret" not in response.text
        with sessions() as db:
            mailbox=db.get(Mailbox,body["id"])
            assert "super-secret" not in mailbox.azure_secret_ciphertext
            configured=mailbox_graph_settings(mailbox)
            assert (configured.azure_client_id,configured.azure_tenant_id,configured.azure_client_secret)==("client-id","tenant-id","super-secret")
        updated=client.patch(f"/api/mailboxes/{body['id']}",json={"display_name":"Owner 2"})
        assert updated.status_code==200 and updated.json()["azure_secret_saved"] is True
        rotated=client.patch(f"/api/mailboxes/{body['id']}",json={"azure_client_secret":"new-secret"})
        assert rotated.status_code==200 and "new-secret" not in rotated.text
        with sessions() as db:assert mailbox_graph_settings(db.get(Mailbox,body["id"])).azure_client_secret=="new-secret"
    engine.dispose()
