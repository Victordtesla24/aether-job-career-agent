"""P3 — networking contacts and outreach tasks."""
from __future__ import annotations


def test_create_contact(client, auth_headers):
    """POST /networking/contacts creates a new contact."""
    payload = {
        "name": "Jane Doe",
        "title": "Senior Engineer",
        "company": "TechCorp",
        "email": "jane@techcorp.com",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "stage": "identified",
    }
    response = client.post("/networking/contacts", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "Jane Doe"
    assert data["title"] == "Senior Engineer"
    assert data["company"] == "TechCorp"
    assert data["email"] == "jane@techcorp.com"
    assert data["linkedinUrl"] == "https://linkedin.com/in/janedoe"
    assert data["stage"] == "identified"
    assert "createdAt" in data
    assert "updatedAt" in data


def test_create_contact_default_stage(client, auth_headers):
    """POST /networking/contacts defaults stage to 'identified'."""
    payload = {"name": "John Smith"}
    response = client.post("/networking/contacts", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["stage"] == "identified"


def test_create_contact_invalid_stage(client, auth_headers):
    """POST /networking/contacts rejects invalid stage."""
    payload = {"name": "Test", "stage": "invalid"}
    response = client.post("/networking/contacts", json=payload, headers=auth_headers)
    assert response.status_code == 422, response.text


def test_list_contacts(client, auth_headers):
    """GET /networking/contacts returns user's contacts."""
    for i in range(2):
        payload = {"name": f"Contact {i}", "company": "Acme"}
        client.post("/networking/contacts", json=payload, headers=auth_headers)
    response = client.get("/networking/contacts", headers=auth_headers)
    assert response.status_code == 200, response.text
    contacts = response.json()
    assert len(contacts) >= 2
    # ordered by updatedAt desc
    assert contacts[0]["name"] == "Contact 1"


def test_list_contacts_filter_stage(client, auth_headers):
    """GET /networking/contacts?stage=identified filters."""
    payload1 = {"name": "Identified", "stage": "identified"}
    payload2 = {"name": "Contacted", "stage": "contacted"}
    client.post("/networking/contacts", json=payload1, headers=auth_headers)
    client.post("/networking/contacts", json=payload2, headers=auth_headers)

    response = client.get("/networking/contacts?stage=identified", headers=auth_headers)
    assert response.status_code == 200, response.text
    contacts = response.json()
    assert len(contacts) == 1
    assert contacts[0]["stage"] == "identified"


def test_list_contacts_filter_company(client, auth_headers):
    """GET /networking/contacts?company=Acme filters."""
    payload1 = {"name": "Alice", "company": "Acme"}
    payload2 = {"name": "Bob", "company": "Beta"}
    client.post("/networking/contacts", json=payload1, headers=auth_headers)
    client.post("/networking/contacts", json=payload2, headers=auth_headers)

    response = client.get("/networking/contacts?company=Acme", headers=auth_headers)
    assert response.status_code == 200, response.text
    contacts = response.json()
    assert len(contacts) == 1
    assert contacts[0]["company"] == "Acme"


def test_get_contact(client, auth_headers):
    """GET /networking/contacts/{contact_id} returns a contact."""
    payload = {"name": "Specific"}
    create = client.post("/networking/contacts", json=payload, headers=auth_headers)
    contact_id = create.json()["id"]

    response = client.get(f"/networking/contacts/{contact_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == contact_id
    assert data["name"] == "Specific"


def test_update_contact(client, auth_headers):
    """PATCH /networking/contacts/{contact_id} updates fields."""
    payload = {"name": "Old"}
    create = client.post("/networking/contacts", json=payload, headers=auth_headers)
    contact_id = create.json()["id"]

    update = {"name": "New", "title": "Engineer"}
    response = client.patch(f"/networking/contacts/{contact_id}", json=update, headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "New"
    assert data["title"] == "Engineer"


def test_delete_contact(client, auth_headers):
    """DELETE /networking/contacts/{contact_id} removes contact."""
    payload = {"name": "To Delete"}
    create = client.post("/networking/contacts", json=payload, headers=auth_headers)
    contact_id = create.json()["id"]

    delete = client.delete(f"/networking/contacts/{contact_id}", headers=auth_headers)
    assert delete.status_code == 204, delete.text

    get = client.get(f"/networking/contacts/{contact_id}", headers=auth_headers)
    assert get.status_code == 404, get.text


def test_create_outreach_task(client, auth_headers):
    """POST /networking/outreach creates outreach task."""
    contact = client.post("/networking/contacts", json={"name": "Contact"}, headers=auth_headers)
    contact_id = contact.json()["id"]

    payload = {
        "contact_id": contact_id,
        "type": "message",
        "message": "Hello",
        "scheduled_at": "2025-01-01T12:00:00Z",
    }
    response = client.post("/networking/outreach", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["contactId"] == contact_id
    assert data["type"] == "message"
    assert data["status"] == "pending"
    assert data["message"] == "Hello"
    assert "createdAt" in data


def test_list_outreach_tasks(client, auth_headers):
    """GET /networking/outreach lists tasks."""
    contact = client.post("/networking/contacts", json={"name": "Contact"}, headers=auth_headers)
    contact_id = contact.json()["id"]
    for i in range(2):
        payload = {"contact_id": contact_id, "type": "message"}
        client.post("/networking/outreach", json=payload, headers=auth_headers)
    response = client.get("/networking/outreach", headers=auth_headers)
    assert response.status_code == 200, response.text
    tasks = response.json()
    assert len(tasks) == 2