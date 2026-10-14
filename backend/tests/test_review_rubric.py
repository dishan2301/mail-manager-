import asyncio
import json
from types import SimpleNamespace

from app.services import review_rubric


def test_rubric_uses_evidence_and_rejects_unsupported_scores(monkeypatch):
    calls=[]
    class Response:
        status_code=200
        def json(self):
            return {"choices":[{"message":{"content":json.dumps({
                "professionalism":{"score":82,"reason":"Reply acknowledged the request."},
                "detail":{"score":None,"reason":"Customer question text unavailable."},
                "clarity":{"score":105,"reason":"Invalid score."},
                "ownership":{"score":70,"reason":"Next step was stated."},
                "actionability":{"score":None,"reason":"No next step was provided."},
            })}}]}
    class Client:
        def __init__(self,**_):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*_):pass
        async def post(self,url,json,headers):
            calls.append(json["model"])
            return Response()
    monkeypatch.setattr(review_rubric.httpx,"AsyncClient",Client)
    settings=SimpleNamespace(ai_api_key="test",ai_api_base_url="https://example.com/v1",ai_model="primary",ai_fallback_model="fallback")
    result=asyncio.run(review_rubric.score_saved_review(settings,"The employee replied with a dated acknowledgement and a next step."))
    assert calls==["primary"]
    assert result["professionalism"]["score"]==82
    assert result["detail"]["score"] is None and result["clarity"]["score"] is None
    missing=asyncio.run(review_rubric.score_saved_review(settings,"Message body unavailable from the mailbox provider."))
    assert all(item["score"] is None for item in missing.values())
    assert calls==["primary"]
