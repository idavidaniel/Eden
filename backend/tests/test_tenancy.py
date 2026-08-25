"""One organisation cannot see, touch, or even confirm the existence of another's.

Auth that stops at a login screen is decoration. These are the tests that decide
whether the scoping underneath it is real, so they are written as attempts to
get at somebody else's data rather than as descriptions of the happy path.
"""

import uuid

import pytest
from starlette.testclient import TestClient

import main
from db import session
from models import Company

PASSWORD = "correct-horse-battery"


@pytest.fixture
def two_organisations():
    """Two signed-in people who have never heard of each other."""
    made = []
    for index in range(2):
        client = TestClient(main.app)
        email = f"tenant-{index}-{uuid.uuid4().hex[:8]}@example.com"
        signed = client.post(
            "/auth/signup",
            json={
                "email": email,
                "password": PASSWORD,
                "full_name": f"Person {index}",
                "organisation": f"Org {index} {uuid.uuid4().hex[:6]}",
            },
        )
        assert signed.status_code == 201, signed.text
        company = client.post(
            "/companies",
            json={"name": f"Company {index}", "starting_team": ["backend_engineer"]},
        )
        assert company.status_code == 201, company.text
        made.append(
            {
                "client": client,
                "email": email,
                "tenant_id": signed.json()["user"]["tenant"]["id"],
                "company": company.json(),
            }
        )
    return made[0], made[1]


# --------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------


def test_you_only_see_your_own_companies(two_organisations):
    mine, theirs = two_organisations

    listed = mine["client"].get("/companies").json()
    ids = {row["id"] for row in listed}
    assert mine["company"]["id"] in ids
    assert theirs["company"]["id"] not in ids, "another tenant's company was listed"


def test_a_company_is_created_inside_your_own_organisation(two_organisations):
    mine, _ = two_organisations
    db = session()
    try:
        row = db.get(Company, mine["company"]["id"])
        assert row.tenant_id == mine["tenant_id"]
    finally:
        db.close()


# --------------------------------------------------------------------------
# reaching directly for an id you should not have
# --------------------------------------------------------------------------


def _paths(company_id: str) -> list[str]:
    return [
        f"/companies/{company_id}",
        f"/companies/{company_id}/employees",
        f"/companies/{company_id}/projects",
        f"/companies/{company_id}/ops",
        f"/companies/{company_id}/inbox",
        f"/companies/{company_id}/ledger",
        f"/companies/{company_id}/artifacts",
        f"/companies/{company_id}/documents",
        f"/companies/{company_id}/channels",
        f"/companies/{company_id}/connections",
        f"/companies/{company_id}/pack",
        f"/companies/{company_id}/tool-calls",
        f"/companies/{company_id}/sources",
        f"/companies/{company_id}/performance",
        f"/companies/{company_id}/meetings",
        f"/companies/{company_id}/messages",
        f"/companies/{company_id}/activity",
        f"/companies/{company_id}/roles",
        f"/companies/{company_id}/authored-tools",
    ]


def test_every_company_read_refuses_another_tenants_id(two_organisations):
    mine, theirs = two_organisations
    for path in _paths(theirs["company"]["id"]):
        response = mine["client"].get(path)
        assert response.status_code == 404, f"{path} answered {response.status_code}"


def test_it_answers_404_rather_than_403(two_organisations):
    """"That exists but is not yours" is itself information."""
    mine, theirs = two_organisations
    real = mine["client"].get(f"/companies/{theirs['company']['id']}")
    invented = mine["client"].get(f"/companies/{uuid.uuid4()}")
    assert real.status_code == invented.status_code == 404
    assert real.json()["detail"] == invented.json()["detail"]


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("patch", "", {"name": "Renamed by a stranger"}),
        ("delete", "", None),
        ("post", "/halt", {"halted": True, "reason": "not yours"}),
        ("post", "/employees", {"role_key": "backend_engineer"}),
        ("post", "/projects", {"name": "Intrusion", "brief": "Should not exist."}),
        ("post", "/documents", {"title": "Nope", "body": "Nope"}),
        ("post", "/pack/reapply", {}),
        ("post", "/ledger/verify", {}),
    ],
)
def test_every_company_write_refuses_another_tenants_id(
    two_organisations, method, suffix, body
):
    mine, theirs = two_organisations
    path = f"/companies/{theirs['company']['id']}{suffix}"
    call = getattr(mine["client"], method)
    response = call(path) if body is None else call(path, json=body)
    assert response.status_code == 404, f"{method} {path} answered {response.status_code}"


def test_a_neighbour_cannot_be_renamed_out_from_under_you(two_organisations):
    mine, theirs = two_organisations
    before = theirs["client"].get(f"/companies/{theirs['company']['id']}").json()["name"]
    mine["client"].patch(
        f"/companies/{theirs['company']['id']}", json={"name": "Renamed by a stranger"}
    )
    after = theirs["client"].get(f"/companies/{theirs['company']['id']}").json()["name"]
    assert after == before


# --------------------------------------------------------------------------
# employees and agents
# --------------------------------------------------------------------------


def test_you_cannot_read_another_tenants_employees(two_organisations):
    mine, theirs = two_organisations
    people = theirs["client"].get(f"/companies/{theirs['company']['id']}/employees").json()
    assert people

    stranger = people[0]["id"]
    assert mine["client"].get(f"/employees/{stranger}").status_code == 404
    assert mine["client"].delete(f"/employees/{stranger}").status_code == 404


def test_you_cannot_mint_a_token_for_another_tenants_agent(two_organisations):
    """The worst version of this bug: taking over somebody else's agent."""
    mine, theirs = two_organisations
    people = theirs["client"].get(f"/companies/{theirs['company']['id']}/employees").json()
    stranger = people[0]["id"]

    minted = mine["client"].post(f"/agents/{stranger}/tokens", json={"name": "theft"})
    assert minted.status_code == 404, "a token was minted for another tenant's agent"


def test_an_agent_token_reaches_only_its_own_company(two_organisations):
    mine, theirs = two_organisations
    my_people = mine["client"].get(f"/companies/{mine['company']['id']}/employees").json()
    secret = mine["client"].post(
        f"/agents/{my_people[0]['id']}/tokens", json={"name": "cli"}
    ).json()["token"]

    with TestClient(main.app) as bare:
        headers = {"Authorization": f"Bearer {secret}"}
        assert bare.get(f"/companies/{mine['company']['id']}", headers=headers).status_code == 200
        assert (
            bare.get(f"/companies/{theirs['company']['id']}", headers=headers).status_code == 404
        )


# --------------------------------------------------------------------------
# projects, work and deliverables
# --------------------------------------------------------------------------


def test_you_cannot_reach_another_tenants_project(two_organisations):
    mine, theirs = two_organisations
    project = theirs["client"].post(
        f"/companies/{theirs['company']['id']}/projects",
        json={"name": "Private", "brief": "Not yours."},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    for path in (
        f"/projects/{project_id}",
        f"/projects/{project_id}/work-items",
        f"/projects/{project_id}/artifacts",
        f"/projects/{project_id}/files",
        f"/projects/{project_id}/work-record",
    ):
        assert mine["client"].get(path).status_code == 404, path

    assert mine["client"].post(f"/projects/{project_id}/runs", json={}).status_code == 404
    assert mine["client"].post(f"/projects/{project_id}/ledger/verify").status_code == 404


def test_you_cannot_reach_another_tenants_work_item(two_organisations):
    mine, theirs = two_organisations
    project_id = theirs["client"].post(
        f"/companies/{theirs['company']['id']}/projects",
        json={"name": "Private", "brief": "Not yours."},
    ).json()["id"]
    item = theirs["client"].post(
        f"/projects/{project_id}/work-items",
        json={"title": "Something private", "kind": "task"},
    )
    assert item.status_code == 201
    item_id = item.json()["id"]

    assert mine["client"].get(f"/work-items/{item_id}").status_code == 404
    assert (
        mine["client"].patch(f"/work-items/{item_id}", json={"status": "done"}).status_code
        == 404
    )
    assert mine["client"].delete(f"/work-items/{item_id}").status_code == 404
    assert mine["client"].post(f"/work-items/{item_id}/checks/run").status_code == 404


# --------------------------------------------------------------------------
# the account itself
# --------------------------------------------------------------------------


def test_your_profile_is_never_somebody_elses(two_organisations):
    mine, theirs = two_organisations
    assert mine["client"].get("/users/me").json()["email"] == mine["email"]
    assert theirs["client"].get("/users/me").json()["email"] == theirs["email"]


def test_signing_out_of_one_organisation_leaves_the_other_alone(two_organisations):
    mine, theirs = two_organisations
    mine["client"].post("/auth/logout")
    assert mine["client"].get("/users/me").status_code in {401, 200}
    assert theirs["client"].get("/users/me").status_code == 200
