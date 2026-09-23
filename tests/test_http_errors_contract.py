"""HTTP method errors use the same validated problem contract as other failures."""

from contracts.models import Problem


def test_method_not_allowed_has_a_valid_client_error_problem() -> None:
    problem = Problem.model_validate_json(
        '{"title":"Method not allowed","status":405,"detail":"Use a supported HTTP method.",'
        '"code":"METHOD_NOT_ALLOWED","request_id":"11111111-1111-4111-8111-111111111111"}'
    )
    assert problem.status == 405
    assert problem.code == "METHOD_NOT_ALLOWED"
