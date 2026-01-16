"""
WAMA Common - Preview Registry

A registry pattern that allows apps to register their models for unified preview functionality.
Each app registers its model with an adapter function that extracts preview data.
"""

import os
import mimetypes
import logging
from typing import Dict, Callable, Any, Optional, Type
from django.db import models

logger = logging.getLogger(__name__)


class PreviewRegistry:
    """
    Central registry for preview adapters.

    Usage:
        # In app's apps.py ready() method:
        PreviewRegistry.register(
            app_name='anonymizer',
            model_class=Media,
            adapter=lambda instance, request: {
                'name': os.path.basename(instance.file.name),
                'url': request.build_absolute_uri(instance.file.url),
                ...
            }
        )
    """

    _registry: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, app_name: str, model_class: Type[models.Model],
                 adapter: Callable[[models.Model, Any], Dict[str, Any]],
                 file_field: str = 'input_file',
                 user_field: str = 'user'):
        """
        Register a model for preview.

        Args:
            app_name: Unique identifier for the app (e.g., 'anonymizer', 'describer')
            model_class: The Django model class
            adapter: Function that takes (instance, request) and returns preview data dict
            file_field: Name of the FileField containing the input file
            user_field: Name of the field containing the user (for permission checks)

        The adapter function should return a dict with:
            - name: str - filename
            - url: str - absolute URL to the file
            - mime_type: str - MIME type (e.g., 'video/mp4')
            - duration: str (optional) - duration display
            - resolution: str (optional) - resolution display
            - properties: str (optional) - additional properties
        """
        cls._registry[app_name] = {
            'model': model_class,
            'adapter': adapter,
            'file_field': file_field,
            'user_field': user_field,
        }
        logger.debug(f"Registered preview adapter for {app_name}: {model_class.__name__}")

    @classmethod
    def get(cls, app_name: str) -> Optional[Dict[str, Any]]:
        """Get registration info for an app."""
        return cls._registry.get(app_name)

    @classmethod
    def get_model(cls, app_name: str) -> Optional[Type[models.Model]]:
        """Get the model class for an app."""
        reg = cls._registry.get(app_name)
        return reg['model'] if reg else None

    @classmethod
    def get_preview_data(cls, app_name: str, instance: models.Model, request) -> Dict[str, Any]:
        """
        Get preview data for an instance using the registered adapter.

        Args:
            app_name: The app identifier
            instance: The model instance
            request: The HTTP request (for building absolute URLs)

        Returns:
            Dict with preview data

        Raises:
            ValueError: If app is not registered
        """
        reg = cls._registry.get(app_name)
        if not reg:
            raise ValueError(f"App '{app_name}' not registered for preview")

        return reg['adapter'](instance, request)

    @classmethod
    def is_registered(cls, app_name: str) -> bool:
        """Check if an app is registered."""
        return app_name in cls._registry

    @classmethod
    def list_registered(cls) -> list:
        """List all registered app names."""
        return list(cls._registry.keys())

    @classmethod
    def check_permission(cls, app_name: str, instance: models.Model, user) -> bool:
        """
        Check if user has permission to view the instance.

        Default implementation checks if instance.user == user or user is staff.
        """
        reg = cls._registry.get(app_name)
        if not reg:
            return False

        user_field = reg.get('user_field', 'user')
        instance_user = getattr(instance, user_field, None)

        if instance_user is None:
            return True  # No user field, allow access

        # Allow if user matches or is staff
        if hasattr(user, 'is_staff') and user.is_staff:
            return True

        return instance_user == user


# Utility functions for creating adapters

def create_simple_adapter(file_field: str = 'input_file',
                          duration_field: str = None,
                          width_field: str = None,
                          height_field: str = None,
                          properties_field: str = None):
    """
    Create a simple adapter function for common model patterns.

    Args:
        file_field: Name of the FileField
        duration_field: Optional name of duration field
        width_field: Optional name of width field
        height_field: Optional name of height field
        properties_field: Optional name of properties field

    Returns:
        An adapter function suitable for PreviewRegistry.register()
    """
    def adapter(instance, request):
        file = getattr(instance, file_field, None)
        if not file:
            return {'error': 'No file available'}

        # Get file path safely
        try:
            file_path = file.path
            mime_type, _ = mimetypes.guess_type(file_path)
        except Exception:
            file_path = None
            mime_type = 'application/octet-stream'

        data = {
            'name': os.path.basename(file.name) if file.name else 'unknown',
            'url': request.build_absolute_uri(file.url),
            'mime_type': mime_type or 'application/octet-stream',
        }

        # Add optional fields
        if duration_field:
            duration = getattr(instance, duration_field, None)
            if duration:
                data['duration'] = str(duration)

        if width_field and height_field:
            width = getattr(instance, width_field, None)
            height = getattr(instance, height_field, None)
            if width and height:
                data['resolution'] = f"{width}x{height}"

        if properties_field:
            props = getattr(instance, properties_field, None)
            if props:
                data['properties'] = str(props)

        return data

    return adapter
