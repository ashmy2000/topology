"""Local, API-key authenticated interface for dependency impact investigation."""

import os
import secrets
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Security
from fastapi.security import APIKeyHeader
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, Field, StringConstraints

from kg import impact_service
from kg.outage import run_read

CIId = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{32}$')]
api_key = APIKeyHeader(name='X-API-Key', auto_error=False)
app = FastAPI(title='Topology Impact Investigator', version='1.0.0')


class Status(BaseModel):
    status: str


class CI(BaseModel):
    sys_id: CIId
    name: str | None
    ci_type: str | None
    source_table: str | None


class SearchResult(BaseModel):
    candidates: list[CI]
    truncated: bool


class ImpactRequest(BaseModel):
    ci_id: CIId = Field(description="Copy the selected candidate's exact sys_id from CI search.")


class Contact(BaseModel):
    contact: str | None
    route: str
    status: Literal['recorded', 'inferred', 'missing']
    business_owner: str | None
    it_application_owner: str | None


class Ownership(BaseModel):
    ci: CI
    contacts: list[Contact]


class EvidencePath(BaseModel):
    names: list[str | None]
    types: list[str]
    node_records: list[list[str | None]]
    link_records: list[list[str | None]]


class AffectedItem(BaseModel):
    sys_id: CIId
    name: str | None
    kind: Literal['business application', 'service']
    status: Literal['down', 'at risk', 'at risk: DR copy lost']
    path: EvidencePath | None
    ownership: Contact
    criticality: str | int | None = None
    dr_copy: str | None = None
    dr_status: str | None = None


class DegradedCluster(BaseModel):
    sys_id: CIId
    name: str | None
    hosts_down: int
    hosts_total: int


class Alert(BaseModel):
    alert: str | None
    source: str | None
    severity: str | None
    ci: str | None
    on_trace: bool
    grouped_under: str | None
    links: list[str]


class ImpactResult(BaseModel):
    failed_ci: CI
    fix: Contact
    affected: list[AffectedItem]
    down_ci_ids: list[CIId]
    at_risk_ci_ids: list[CIId]
    additional_cis_down: int
    degraded_clusters: list[DegradedCluster]
    alerts: list[Alert]
    ownership_gap_ci_ids: list[CIId]
    uncertainty: list[str]
    human_review_required: Literal[True]


def require_key(provided: Annotated[str | None, Security(api_key)]) -> None:
    expected = os.getenv('IMPACT_API_KEY', '')
    if len(expected) < 32:
        raise HTTPException(503, 'API authentication is unavailable')
    if not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(401, 'Missing or invalid API key')


protected = [Depends(require_key)]


@app.get('/health', response_model=Status, operation_id='getHealth')
def health():
    return {'status': 'ok'}


@app.get('/ready', response_model=Status, operation_id='getReadiness')
def ready():
    try:
        run_read('RETURN 1 AS ready')
    except (DriverError, Neo4jError):
        raise HTTPException(503, 'Graph database unavailable') from None
    return {'status': 'ready'}


@app.get('/api/v1/cis/search', response_model=SearchResult, dependencies=protected, operation_id='searchCIs')
def search_cis(
    query: Annotated[str, StringConstraints(strip_whitespace=True), Query(min_length=1, max_length=120)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    try:
        candidates = impact_service.search(query, limit + 1)
    except (DriverError, Neo4jError):
        raise HTTPException(503, 'Graph database unavailable') from None
    return {'candidates': candidates[:limit], 'truncated': len(candidates) > limit}


@app.post('/api/v1/impact', response_model=ImpactResult, dependencies=protected, operation_id='assessImpact')
def assess_impact(request: ImpactRequest):
    try:
        return impact_service.assess(request.ci_id)
    except impact_service.UnknownCI:
        raise HTTPException(404, 'CI not found') from None
    except (DriverError, Neo4jError):
        raise HTTPException(503, 'Graph database unavailable') from None


@app.get('/api/v1/cis/{ci_id}/ownership', response_model=Ownership, dependencies=protected, operation_id='getCIOwnership')
def get_ci_ownership(ci_id: Annotated[CIId, Path()]):
    try:
        return impact_service.ownership(ci_id)
    except impact_service.UnknownCI:
        raise HTTPException(404, 'CI not found') from None
    except (DriverError, Neo4jError):
        raise HTTPException(503, 'Graph database unavailable') from None
