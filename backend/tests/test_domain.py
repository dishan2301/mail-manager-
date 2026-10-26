from datetime import date,datetime,time,timezone
from app.models.entities import Classification,SLATier
from app.services.classification import Rule,classify
from app.services.reply_detection import MessageRef,is_reply
from app.services.sla import Calendar,business_hours_between,elapsed_hours,tier_for
from app.services.escalation import Threshold,newly_crossed
from app.schemas.api import CalendarInput,ClassificationRuleInput
from app.services.sync import _recipients
from pydantic import ValidationError
import pytest
def test_unmatched_defaults_to_customer_and_autoreply_wins():
    rules=[Rule(10,"subject",r"sale",Classification.MARKETING)]
    assert classify("person@client.com","Need help",{},rules)==Classification.CUSTOMER
    assert classify("bot@client.com","Need help",{"Auto-Submitted":"auto-replied"},rules)==Classification.AUTO_REPLY
def test_allowlist_and_blocklist_rules_run_before_auto_reply_headers():
    rules=[Rule(1,"sender",r"^trusted@",Classification.CUSTOMER),Rule(2,"domain",r"blocked\.example$",Classification.IGNORE)]
    headers={"Auto-Submitted":"auto-replied"}
    assert classify("trusted@client.com","Automatic notice",headers,rules)==Classification.CUSTOMER
    assert classify("bot@blocked.example","Automatic notice",headers,rules)==Classification.IGNORE
def test_reply_primary_header_and_bounded_fallback():
    start=datetime(2026,7,1,tzinfo=timezone.utc);incoming=MessageRef("<a@x>","c1","Invoice",start)
    assert is_reply(incoming,MessageRef("<b@x>","different","Re: Invoice",start.replace(day=2),in_reply_to="<a@x>"))
    assert not is_reply(incoming,MessageRef("<b@x>","c1","Re: Invoice",start.replace(month=9)))
    assert is_reply(incoming,MessageRef("<b@x>","c1","RE: Re: Invoice",start.replace(day=2)))
def test_business_hours_skip_weekend_and_tiers():
    cal=Calendar(start=time(9),end=time(18),holidays=frozenset({date(2026,7,13)}));friday=datetime(2026,7,10,12,tzinfo=timezone.utc);tuesday=datetime(2026,7,14,6,tzinfo=timezone.utc)
    assert business_hours_between(friday,tuesday,cal)==3.0
    assert elapsed_hours(friday.replace(tzinfo=None),tuesday.replace(tzinfo=None),cal,False)==90.0
    assert tier_for(24)==SLATier.CRITICAL and tier_for(7)==SLATier.WARNING
def test_escalations_only_return_new_threshold_crossings():
    thresholds=[Threshold("manager-8h",8,"Manager"),Threshold("director-24h",24,"Director")]
    assert [x.name for x in newly_crossed(30,{"manager-8h"},thresholds)]==["director-24h"]
    assert newly_crossed(30,{"manager-8h","director-24h"},thresholds)==[]
def test_settings_reject_invalid_regex_and_business_calendar():
    with pytest.raises(ValidationError):ClassificationRuleInput(name="Broken",priority=1,field="subject",pattern="[",classification=Classification.IGNORE)
    with pytest.raises(ValidationError):CalendarInput(timezone="Asia/Kolkata",workday_start="18:00",workday_end="09:00")
def test_graph_recipients_are_persisted_instead_of_mailbox_fallback():
    item={"toRecipients":[{"emailAddress":{"address":"first@example.com"}},{"emailAddress":{"address":"second@example.com"}}]}
    assert _recipients(item,"support@example.com")=="first@example.com, second@example.com"
    assert _recipients({},"support@example.com")==""
