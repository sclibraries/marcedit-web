"""The authenticated API identity endpoint."""

from flask import g, jsonify


def get_me():
    access = g.api_access
    return jsonify(
        {
            "email": access.email,
            "outcome": access.outcome,
            "role": access.role,
            "version": 1,
        }
    )
