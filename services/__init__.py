"""
Services package for external integrations and persistence.

Exports:
    RoutesServiceClient   – Google Routes API v2 client with simulation fallback.
    FirestoreRepository   – Firestore + local JSON dual-mode persistence layer.
"""

from services.google_services import RoutesServiceClient, FirestoreRepository

__all__ = ["RoutesServiceClient", "FirestoreRepository"]
