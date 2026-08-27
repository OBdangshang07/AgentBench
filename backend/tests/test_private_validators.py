from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from agentbench.execution import CommandResult, Workspace
from agentbench.private_validators import (
    PrivateValidatorError,
    PrivateValidatorStore,
    install_private_validator_bundle,
)
from agentbench.scoring import ScoringEngine
from agentbench.service import public_definition


def _bundle(tmp_path, *, content: str = "print('validator')\n"):
    root = tmp_path / "private-validators"
    bundle = root / "backend-ultra-extreme" / "1.0.0"
    bundle.mkdir(parents=True)
    script = bundle / "validate.py"
    script.write_bytes(content.encode("utf-8"))
    manifest = {
        "schema_version": 1,
        "bundle_id": "backend-ultra-extreme",
        "version": "1.0.0",
        "validators": {
            "ledger": {
                "command": "python {private_root}/validate.py --seed {validation_seed}",
                "files": {
                    "validate.py": hashlib.sha256(content.encode("utf-8")).hexdigest()
                },
            }
        },
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    (bundle / "manifest.json").write_bytes(manifest_bytes)
    reference = {
        "bundle_id": "backend-ultra-extreme",
        "version": "1.0.0",
        "validator_id": "ledger",
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    return root, reference


def test_private_validator_store_resolves_only_digest_pinned_files(tmp_path):
    root, reference = _bundle(tmp_path)
    resolved = PrivateValidatorStore(root).resolve(reference)

    assert resolved.files == {"validate.py": "print('validator')\n"}
    assert resolved.command.endswith("--seed {validation_seed}")
    assert resolved.provenance["manifest_sha256"] == reference["manifest_sha256"]

    (root / "backend-ultra-extreme" / "1.0.0" / "validate.py").write_text(
        "tampered\n", encoding="utf-8"
    )
    with pytest.raises(PrivateValidatorError, match="integrity"):
        PrivateValidatorStore(root).resolve(reference)


def test_private_validator_archive_installs_below_user_data(tmp_path):
    source_root, reference = _bundle(tmp_path / "source")
    source = source_root / "backend-ultra-extreme" / "1.0.0"
    archive = tmp_path / "backend-ultra.abpv"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(source / "manifest.json", "manifest.json")
        bundle.write(source / "validate.py", "validate.py")

    target = tmp_path / "user-data" / "private-validators"
    installed = install_private_validator_bundle(archive, target)

    assert installed["manifest_sha256"] == reference["manifest_sha256"]
    assert PrivateValidatorStore(target).resolve(reference).files["validate.py"].startswith(
        "print"
    )


def test_private_metrics_apply_hard_gate_and_quality_only_score(tmp_path):
    root, reference = _bundle(tmp_path)

    class FakeDocker:
        def run(self, workspace, command, _image, **kwargs):
            assert "--seed " + "a" * 64 in command
            injected = command.split()[1]
            assert workspace.read_file(injected) == "print('validator')\n"
            assert kwargs["cpus"] == 4.0
            assert kwargs["memory"] == "8g"
            return CommandResult(
                True,
                0,
                'AGENTBENCH_METRICS={"metrics":{"correctness":95,"performance":100},'
                '"hard_failures":["data_loss"],"evidence":{"correctness":{"ok":19}}}\n',
                "",
                5,
            )

    definition = {
        "metadata": {"score_basis": "backend_quality"},
        "limits": {
            "max_steps": 100,
            "token_budget": 60_000,
            "_validation_seed": "a" * 64,
            "validator_cpus": 4,
            "validator_memory": "8g",
        },
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "private_validator_ref": reference,
                    "metrics": [
                        {"key": "correctness", "name": "正确性", "weight": 90},
                        {"key": "performance", "name": "性能", "weight": 10},
                    ],
                    "hard_caps": [
                        {"key": "data_loss", "max_score": 40, "reason": "数据丢失"}
                    ],
                },
            }
        ],
    }
    score = ScoringEngine(FakeDocker(), PrivateValidatorStore(root)).score(
        definition=definition,
        final_answer="done",
        workspace=Workspace(tmp_path / "workspace"),
        steps=80,
        duration_ms=9_999_999,
        tokens_input=50_000,
        tokens_output=50_000,
    )

    assert score.score == 40
    assert next(item for item in score.components if item.validator_type == "hard_gate").evidence[
        "score_before_cap"
    ] == 95.5
    objective = next(
        item for item in score.dimensions if item.validator_type == "objective_quality"
    )
    assert objective.score == 40
    assert not any(
        item.validator_type in {"time_efficiency", "step_efficiency", "token_efficiency"}
        for item in score.dimensions
    )


def test_public_definition_keeps_provenance_but_hides_private_command(tmp_path):
    _root, reference = _bundle(tmp_path)
    definition = {
        "metadata": {"demo_actions": [{"secret": True}]},
        "validators": [
            {
                "type": "command_metrics",
                "weight": 100,
                "config": {
                    "command": "python hidden.py",
                    "private_validator_ref": reference,
                    "metrics": [{"key": "correctness", "weight": 100}],
                },
            }
        ],
    }

    public = public_definition(definition)

    config = public["validators"][0]["config"]
    assert config["command"] == "<AgentBench private validator>"
    assert config["private"] is True
    assert config["private_validator_ref"] == reference
    assert "demo_actions" not in public["metadata"]
