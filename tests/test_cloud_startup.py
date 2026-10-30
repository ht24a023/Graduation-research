"""APIキーがなくてもローカル起動でき、クラウド利用時にだけ検査する。"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cloud import openai_client


def test_import_entry_points_without_api_key():
    env = dict(os.environ, OPENAI_API_KEY='', OPENAI_ADMIN_KEY='')
    result = subprocess.run(
        [sys.executable, '-c', 'import main; import local_ai_server; import mcp_server'],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_cloud_without_key_fails_before_creating_connection():
    with patch.object(openai_client, 'OPENAI_API_KEY', '  '), patch.object(openai_client, 'OpenAI') as factory:
        with pytest.raises(RuntimeError, match='APIキーが未設定'):
            openai_client.ask_cloud_ai('test')
        factory.assert_not_called()


def test_cloud_initializes_on_demand_and_reuses_connection():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices[0].message.content = 'answer'
    openai_client._get_client.cache_clear()
    try:
        with patch.object(openai_client, 'OPENAI_API_KEY', 'test-key'), patch.object(openai_client, 'OpenAI', return_value=fake_client) as factory:
            factory.assert_not_called()
            assert openai_client.ask_cloud_ai('first') == 'answer'
            assert openai_client.ask_cloud_ai('second') == 'answer'
            factory.assert_called_once_with(api_key='test-key')
            fake_client.chat.completions.create.assert_called_with(
                model='gpt-4.1-mini', messages=[{'role': 'user', 'content': 'second'}],
            )
    finally:
        openai_client._get_client.cache_clear()
