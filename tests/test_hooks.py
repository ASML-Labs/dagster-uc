"""Tests for hook template variable substitution."""

import os
from unittest.mock import MagicMock, patch

import pytest

from dagster_uc.config import HookScript
from dagster_uc.manage_user_code_deployments import (
    HOOK_TEMPLATE_PATTERN,
    render_hook_template,
    run_hook_script,
    run_hook_scripts,
)


class TestRenderHookTemplate:
    """Tests for the render_hook_template function."""

    def test_simple_variable_substitution_lowercase(self):
        """Test that {{ variable }} is replaced with its value (lowercase)."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("{{ environment }}", template_vars)
        assert result == "dev"

    def test_simple_variable_substitution_uppercase(self):
        """Test that {{ VARIABLE }} is replaced with its value (uppercase)."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("{{ ENVIRONMENT }}", template_vars)
        assert result == "dev"

    def test_simple_variable_substitution_mixed_case(self):
        """Test that {{ Variable }} is replaced with its value (mixed case)."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("{{ Environment }}", template_vars)
        assert result == "dev"

    def test_variable_in_larger_string(self):
        """Test that variables work when embedded in larger strings."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("environment={{ environment }}", template_vars)
        assert result == "environment=dev"

    def test_multiple_variables_in_one_string(self):
        """Test multiple placeholders in a single string."""
        template_vars = {"image": "myimage", "tag": "v1.0"}
        result = render_hook_template("{{ image }}:{{ tag }}", template_vars)
        assert result == "myimage:v1.0"

    def test_no_whitespace_inside_braces(self):
        """Test that {{VAR}} works (no whitespace)."""
        template_vars = {"var": "value"}
        result = render_hook_template("{{var}}", template_vars)
        assert result == "value"

    def test_whitespace_inside_braces(self):
        """Test that {{ var }} works (with whitespace)."""
        template_vars = {"var": "value"}
        result = render_hook_template("{{ var }}", template_vars)
        assert result == "value"

    def test_extra_whitespace_inside_braces(self):
        """Test that {{   var   }} works (extra whitespace)."""
        template_vars = {"var": "value"}
        result = render_hook_template("{{   var   }}", template_vars)
        assert result == "value"

    def test_unknown_variable_raises_error(self):
        """Test that unknown variables raise ValueError."""
        template_vars = {"known": "value"}
        with pytest.raises(ValueError) as exc_info:
            render_hook_template("{{ unknown }}", template_vars)
        assert "unknown" in str(exc_info.value)
        assert "Available variables" in str(exc_info.value)
        assert "known" in str(exc_info.value)

    def test_unknown_variable_uppercase_raises_error(self):
        """Test that unknown uppercase variables raise ValueError."""
        template_vars = {"environment": "dev"}
        with pytest.raises(ValueError) as exc_info:
            render_hook_template("{{ FOOBAR }}", template_vars)
        assert "FOOBAR" in str(exc_info.value)

    def test_no_placeholders_returns_unchanged(self):
        """Test that strings without placeholders are returned unchanged."""
        template_vars = {"var": "value"}
        result = render_hook_template("plain string", template_vars)
        assert result == "plain string"

    def test_empty_string(self):
        """Test that empty string works."""
        template_vars = {"var": "value"}
        result = render_hook_template("", template_vars)
        assert result == ""

    def test_all_canonical_variables(self):
        """Test all canonical variables."""
        template_vars = {
            "image_name": "myproject--feat-branch",
            "image_tag": "0.1.0+branch.feat-branch.abc123",
            "full_image": "ghcr.io/myorg/myproject--feat-branch:0.1.0+branch.feat-branch.abc123",
            "deployment_name": "my-deployment",
            "branch_name": "feat-branch",
            "registry": "ghcr.io/myorg",
            "environment": "dev",
        }
        # Test lowercase
        assert render_hook_template("{{ image_name }}", template_vars) == "myproject--feat-branch"
        assert render_hook_template("{{ image_tag }}", template_vars) == "0.1.0+branch.feat-branch.abc123"
        assert (
            render_hook_template("{{ full_image }}", template_vars)
            == "ghcr.io/myorg/myproject--feat-branch:0.1.0+branch.feat-branch.abc123"
        )
        assert render_hook_template("{{ deployment_name }}", template_vars) == "my-deployment"
        assert render_hook_template("{{ branch_name }}", template_vars) == "feat-branch"
        assert render_hook_template("{{ registry }}", template_vars) == "ghcr.io/myorg"
        assert render_hook_template("{{ environment }}", template_vars) == "dev"

    def test_all_canonical_variables_uppercase(self):
        """Test all canonical variables in uppercase."""
        template_vars = {
            "image_name": "myproject--feat-branch",
            "image_tag": "0.1.0",
            "full_image": "registry.io/myproject--feat-branch:0.1.0",
            "deployment_name": "my-deployment",
            "branch_name": "feat-branch",
            "registry": "registry.io",
            "environment": "dev",
        }
        # Test uppercase
        assert render_hook_template("{{ IMAGE_NAME }}", template_vars) == "myproject--feat-branch"
        assert render_hook_template("{{ IMAGE_TAG }}", template_vars) == "0.1.0"
        assert (
            render_hook_template("{{ FULL_IMAGE }}", template_vars)
            == "registry.io/myproject--feat-branch:0.1.0"
        )
        assert render_hook_template("{{ DEPLOYMENT_NAME }}", template_vars) == "my-deployment"
        assert render_hook_template("{{ BRANCH_NAME }}", template_vars) == "feat-branch"
        assert render_hook_template("{{ REGISTRY }}", template_vars) == "registry.io"
        assert render_hook_template("{{ ENVIRONMENT }}", template_vars) == "dev"

    def test_complex_real_world_example(self):
        """Test a complex real-world example."""
        template_vars = {
            "full_image": "ghcr.io/myorg/myapp:v1.0.0",
            "deployment_name": "my-deployment",
            "environment": "prod",
        }
        result = render_hook_template(
            "--image {{ full_image }} --deployment {{ deployment_name }} --env {{ environment }}",
            template_vars,
        )
        assert result == "--image ghcr.io/myorg/myapp:v1.0.0 --deployment my-deployment --env prod"


class TestHookPattern:
    """Tests for the HOOK_TEMPLATE_PATTERN regex."""

    def test_pattern_matches_double_braces(self):
        """Test that the pattern matches {{ VAR }}."""
        assert HOOK_TEMPLATE_PATTERN.search("{{ var }}") is not None

    def test_pattern_captures_variable_name(self):
        """Test that the pattern captures the variable name."""
        match = HOOK_TEMPLATE_PATTERN.search("{{ var }}")
        assert match is not None
        assert match.group(1) == "var"

    def test_pattern_matches_with_whitespace(self):
        """Test that the pattern matches with whitespace."""
        match = HOOK_TEMPLATE_PATTERN.search("{{ var }}")
        assert match is not None
        assert match.group(1) == "var"

    def test_pattern_matches_without_whitespace(self):
        """Test that the pattern matches without whitespace."""
        match = HOOK_TEMPLATE_PATTERN.search("{{var}}")
        assert match is not None
        assert match.group(1) == "var"

    def test_pattern_matches_underscores(self):
        """Test that the pattern matches variables with underscores."""
        match = HOOK_TEMPLATE_PATTERN.search("{{ full_image }}")
        assert match is not None
        assert match.group(1) == "full_image"

    def test_pattern_does_not_match_single_brace(self):
        """Test that the pattern doesn't match single braces."""
        assert HOOK_TEMPLATE_PATTERN.search("{ var }") is None
        assert HOOK_TEMPLATE_PATTERN.search("{{ var ") is None
        assert HOOK_TEMPLATE_PATTERN.search("var }}") is None


class TestCaseInsensitiveVariables:
    """Tests for case-insensitive hook template variable lookup."""

    def test_lowercase_variable(self):
        """Test lowercase variable names."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("{{ environment }}", template_vars)
        assert result == "dev"

    def test_uppercase_variable(self):
        """Test uppercase variable names."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("{{ ENVIRONMENT }}", template_vars)
        assert result == "dev"

    def test_mixed_case_variable(self):
        """Test mixed case variable names."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("{{ Environment }}", template_vars)
        assert result == "dev"


class TestEmbeddedSubstitution:
    """Tests for embedded template substitution."""

    def test_embedded_lowercase(self):
        """Test embedded substitution with lowercase."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("environment={{ environment }}", template_vars)
        assert result == "environment=dev"

    def test_embedded_uppercase(self):
        """Test embedded substitution with uppercase."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("environment={{ ENVIRONMENT }}", template_vars)
        assert result == "environment=dev"

    def test_full_image_substitution(self):
        """Test full image substitution."""
        template_vars = {"full_image": "example.azurecr.io/simba/foo:123"}
        result = render_hook_template("imageName={{ FULL_IMAGE }}", template_vars)
        assert result == "imageName=example.azurecr.io/simba/foo:123"


class TestWhitespaceVariations:
    """Tests for optional whitespace in template variables."""

    def test_no_whitespace(self):
        """Test {{VAR}} without whitespace."""
        template_vars = {"var": "value"}
        result = render_hook_template("{{var}}", template_vars)
        assert result == "value"

    def test_single_space(self):
        """Test {{ VAR }} with single space."""
        template_vars = {"var": "value"}
        result = render_hook_template("{{ var }}", template_vars)
        assert result == "value"

    def test_extra_whitespace(self):
        """Test {{   VAR   }} with extra whitespace."""
        template_vars = {"var": "value"}
        result = render_hook_template("{{   var   }}", template_vars)
        assert result == "value"


class TestMultiplePlaceholders:
    """Tests for multiple placeholders in one string."""

    def test_multiple_placeholders(self):
        """Test multiple placeholders in one string."""
        template_vars = {"env": "dev", "image": "myimage"}
        result = render_hook_template("env={{ env }} image={{ image }}", template_vars)
        assert result == "env=dev image=myimage"

    def test_multiple_same_placeholder(self):
        """Test same placeholder used multiple times."""
        template_vars = {"var": "value"}
        result = render_hook_template("{{ var }} and {{ var }}", template_vars)
        assert result == "value and value"


class TestScriptPathInterpolation:
    """Tests for script path interpolation."""

    def test_script_path_with_variable(self):
        """Test script path with template variable."""
        template_vars = {"environment": "prod"}
        result = render_hook_template("scripts/{{ environment }}/deploy.py", template_vars)
        assert result == "scripts/prod/deploy.py"

    def test_script_path_uppercase_variable(self):
        """Test script path with uppercase template variable."""
        template_vars = {"environment": "prod"}
        result = render_hook_template("scripts/{{ ENVIRONMENT }}/deploy.py", template_vars)
        assert result == "scripts/prod/deploy.py"


class TestUnknownVariables:
    """Tests for unknown variable handling."""

    def test_unknown_variable_raises_error_with_available(self):
        """Test that unknown variables raise ValueError with available variables."""
        template_vars = {"known": "value"}
        with pytest.raises(ValueError) as exc_info:
            render_hook_template("{{ unknown }}", template_vars)
        error_msg = str(exc_info.value)
        assert "unknown" in error_msg
        assert "Available variables" in error_msg
        assert "known" in error_msg

    def test_unknown_variable_case_insensitive_error(self):
        """Test that unknown variables raise error regardless of case."""
        template_vars = {"environment": "dev"}
        with pytest.raises(ValueError) as exc_info:
            render_hook_template("{{ FOOBAR }}", template_vars)
        assert "FOOBAR" in str(exc_info.value)

    def test_unknown_variable_does_not_reach_subprocess(self):
        """Test that unknown variables fail before subprocess execution."""
        hook = HookScript(script="echo hello", args=["{{ unknown_var }}"])
        template_vars = {"environment": "dev"}
        
        with pytest.raises(ValueError) as exc_info:
            run_hook_script(hook, template_vars)
        assert "unknown_var" in str(exc_info.value)


class TestNoPlaceholders:
    """Tests for hooks without placeholders."""

    def test_no_placeholders_remains_unchanged(self):
        """Test that strings without placeholders remain unchanged."""
        template_vars = {"environment": "dev"}
        result = render_hook_template("plain string", template_vars)
        assert result == "plain string"

    def test_empty_args_list(self):
        """Test hook with empty args list."""
        hook = HookScript(script="tests/test_hooks.py", args=[])
        
        with patch("dagster_uc.manage_user_code_deployments.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            result = run_hook_script(hook, {})
            assert result is True


class TestUnresolvedPlaceholderValidation:
    """Tests for defensive validation of unresolved placeholders."""

    def test_unresolved_placeholder_raises_error(self):
        """Test that unresolved placeholders raise ValueError."""
        template_vars = {"known": "value"}
        with pytest.raises(ValueError) as exc_info:
            render_hook_template("{{ unknown }}", template_vars)
        error_msg = str(exc_info.value)
        assert "Unresolved" in error_msg or "Unknown" in error_msg


class TestOSEnvironmentVariables:
    """Tests to ensure ${...} config substitution continues to work."""

    def test_dollar_syntax_not_affected(self):
        """Test that ${...} syntax is not affected by hook template changes."""
        template_vars = {"var": "value"}
        result = render_hook_template("${CONTAINER_REGISTRY}", template_vars)
        # ${...} should remain unchanged
        assert result == "${CONTAINER_REGISTRY}"


class TestSubprocessArguments:
    """Tests for subprocess argument rendering."""

    def test_subprocess_receives_rendered_args(self):
        """Test that subprocess receives fully rendered arguments."""
        hook = HookScript(
            script="scripts/deploy.py",
            args=["--param", "environment={{ ENVIRONMENT }}", "--param", "imageName={{ FULL_IMAGE }}"]
        )
        template_vars = {
            "environment": "dev",
            "full_image": "example.azurecr.io/simba/foo:123",
        }
        
        with patch("dagster_uc.manage_user_code_deployments.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            result = run_hook_script(hook, template_vars)
            
            # Verify subprocess.run was called with rendered arguments
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            
            # Check the command contains the rendered values
            assert "scripts/deploy.py" in call_args
            assert "--param" in call_args
            assert "environment=dev" in call_args
            assert "imageName=example.azurecr.io/simba/foo:123" in call_args
            
            # Ensure no unresolved placeholders
            for arg in call_args:
                assert "{{" not in arg
            
            assert result is True

    def test_subprocess_receives_rendered_script_path(self):
        """Test that subprocess receives rendered script path."""
        hook = HookScript(
            script="scripts/{{ environment }}/deploy.py",
            args=[]
        )
        template_vars = {"environment": "prod"}
        
        with patch("dagster_uc.manage_user_code_deployments.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_result.returncode = 0
            mock_run.return_value = mock_result
            
            result = run_hook_script(hook, template_vars)
            
            # Verify the script path is rendered
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert "scripts/prod/deploy.py" in call_args
            assert "{{" not in call_args[0]  # Script path should not have placeholders
            
            assert result is True