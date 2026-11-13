import pytest

from app import create_app
from generate import generate_dataset


@pytest.fixture()
def client(tmp_path):
    dataset = tmp_path / "dataset"
    generate_dataset(
        dataset,
        {"campaigns": 8, "contacts": 40, "touchpoints": 180, "opportunities": 25},
        seed=20261022,
    )
    application = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "DATASET_DIR": str(dataset),
        "BASE_CURRENCY": "INR",
    })
    with application.test_client() as test_client:
        response = test_client.get("/register")
        assert response.status_code == 200
        with test_client.session_transaction() as browser_session:
            csrf_token = browser_session["csrf_token"]
        response = test_client.post(
            "/register",
            data={
                "csrf_token": csrf_token,
                "email": "analytics@example.test",
                "password": "Correct-horse-9!",
                "confirm_password": "Correct-horse-9!",
            },
        )
        assert response.status_code == 302
        response = test_client.get("/login")
        with test_client.session_transaction() as browser_session:
            csrf_token = browser_session["csrf_token"]
        response = test_client.post(
            "/login",
            data={
                "csrf_token": csrf_token,
                "email": "analytics@example.test",
                "password": "Correct-horse-9!",
            },
        )
        assert response.status_code == 302
        yield test_client
