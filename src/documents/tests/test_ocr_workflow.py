from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.data_models import DocumentSource
from documents.models import Workflow
from documents.models import WorkflowAction
from documents.models import WorkflowTrigger
from documents.signals.handlers import run_workflows


class TestOCRWorkflow(TestCase):
    @patch("documents.data_models.magic.from_file")
    def test_ocr_engine_assignment_to_overrides(self, mock_magic):
        mock_magic.return_value = "application/pdf"
        # 1. Setup workflow
        workflow = Workflow.objects.create(name="OCR Workflow")
        trigger = WorkflowTrigger.objects.create(
            type=WorkflowTrigger.WorkflowTriggerType.CONSUMPTION,
            filter_filename="invoice*.pdf",
        )
        workflow.triggers.add(trigger)

        action = WorkflowAction.objects.create(
            type=WorkflowAction.WorkflowActionType.ASSIGNMENT,
            assign_ocr_engine="docling",
        )
        workflow.actions.add(action)

        # 2. Simulate consumable document
        input_doc = ConsumableDocument(
            source=DocumentSource.ConsumeFolder,
            original_file=Path("invoice_123.pdf"),
        )

        # 3. Run workflows
        overrides = DocumentMetadataOverrides()
        result_overrides, _ = run_workflows(
            trigger_type=WorkflowTrigger.WorkflowTriggerType.CONSUMPTION,
            document=input_doc,
            overrides=overrides,
        )

        # 4. Verify
        self.assertEqual(result_overrides.ocr_engine, "docling")
