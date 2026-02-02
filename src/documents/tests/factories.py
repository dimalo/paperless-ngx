from factory.django import DjangoModelFactory
from factory.faker import Faker

from documents.models import AIReviewQueue
from documents.models import AISuggestionHistory
from documents.models import Correspondent
from documents.models import Document


class CorrespondentFactory(DjangoModelFactory):
    class Meta:
        model = Correspondent

    name = Faker("name")


class DocumentFactory(DjangoModelFactory):
    class Meta:
        model = Document

    checksum = Faker("md5")
    title = Faker("sentence", nb_words=4)


class AIReviewQueueFactory(DjangoModelFactory):
    class Meta:
        model = AIReviewQueue

    suggestions = {
        "title": {"value": "Test Title", "confidence": 0.6},
        "tags": [{"value": "test-tag", "confidence": 0.6}],
    }
    confidence_scores = {
        "title": 0.6,
        "tags": [0.6],
    }


class AISuggestionHistoryFactory(DjangoModelFactory):
    class Meta:
        model = AISuggestionHistory

    applied_suggestions = {
        "title": {"value": "AI Applied Title", "confidence": 0.8},
        "tags": ["ai-tag"],
    }
    confidence_scores = {
        "title": 0.8,
        "tags": [0.8],
    }
