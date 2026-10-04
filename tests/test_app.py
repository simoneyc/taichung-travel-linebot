import os
from types import SimpleNamespace as NS
from unittest.mock import Mock
from urllib.parse import urlencode

os.environ['CHANNEL_ACCESS_TOKEN'] = 'test-token'
os.environ['CHANNEL_SECRET'] = 'test-secret'
import app
import requests
import pytest

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in ('user_mode', 'user_region', 'user_category', 'new_data',
                 'game_data', 'user_scores', 'question_index', 'user_answers'):
        getattr(app, name).clear()
    monkeypatch.setattr(app, 'line_bot_api', Mock())


def message(user, text):
    return NS(source=NS(user_id=user), message=NS(text=text), reply_token='reply')


def postback(user, data):
    return NS(source=NS(user_id=user), postback=NS(data=data), reply_token='reply')


def test_missing_signature():
    assert app.app.test_client().post('/callback', json={}).status_code == 400


def test_invalid_signature():
    assert app.app.test_client().post('/callback', data='{}', headers={'X-Line-Signature': 'invalid'}).status_code == 400


def test_user_modes_are_isolated(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_ID', 'test-admin')
    app.handle_message(message('a', '推薦'))
    app.handle_message(message('b', '新增'))
    assert app.user_mode == {'a': '推薦', 'b': '新增'}
    app.handle_message(message('a', 'hello'))
    assert 'a' not in app.new_data


def test_empty_recommendations():
    assert app.create_flex_message([]).text


def test_missing_image_and_encoded_title():
    app.user_category['a'] = '美食'
    app.user_region['a'] = '北區'
    payload = app.create_flex_message([{'Title': 'A&B=C', 'Image Link': 'javascript:bad'}], 'a').as_json_dict()
    bubble = payload['contents']['contents'][0]
    assert 'hero' not in bubble
    assert 'A%26B%3DC' in str(payload)


def test_weather_timeout(monkeypatch):
    monkeypatch.setattr(app.requests, 'get', Mock(side_effect=requests.Timeout))
    assert app.get_weather_info('北區') is None


def test_weather_changed_html(monkeypatch):
    monkeypatch.setattr(app.requests, 'get', Mock(return_value=NS(status_code=200, text='<div></div>')))
    assert app.get_weather_info('北區') == {}


def test_no_quiz_questions(monkeypatch):
    monkeypatch.setattr(app, 'get_game_questions', lambda: [])
    app.handle_message(message('a', '知識王'))
    app.line_bot_api.reply_message.assert_called_once()


def test_duplicate_quiz_answer():
    app.game_data['a'] = [dict(Question='q', A='a&b', B='b', C='c', D='d', Answer='a&b')]*2
    app.question_index['a'] = 0
    app.user_scores['a'] = 0
    app.user_answers['a'] = []
    event = postback('a', urlencode({'game_answer': 0, 'choice': 'a&b'}))
    app.handle_postback(event)
    app.handle_postback(event)
    assert app.user_scores['a'] == 1
    assert app.question_index['a'] == 1
    app.line_bot_api.push_message.assert_not_called()


@pytest.mark.parametrize('data', ['rating=99&title=x', 'region=invalid', 'game_answer=999&choice=a', 'rating=1&rating=2', 'bad'])
def test_invalid_postbacks(data):
    app.handle_postback(postback('a', data))
    app.line_bot_api.reply_message.assert_called_once()


def test_weather_failure_keeps_recommendations(monkeypatch):
    app.user_mode['a'] = '推薦'
    app.user_region['a'] = '北區'
    monkeypatch.setattr(app, 'get_top_rated_items_from_db', lambda *args: [])
    monkeypatch.setattr(app, 'get_weather_info', lambda *args: None)
    app.handle_message(message('a', '景點'))
    assert len(app.line_bot_api.reply_message.call_args.args[1]) == 2


def test_atomic_rating(monkeypatch):
    collection = Mock()
    collection.update_one.return_value.matched_count = 1
    monkeypatch.setattr(app, 'get_database', lambda category: {'北區': collection})
    assert app.handle_rating('a', 'place', '5', '美食', '北區')
    assert isinstance(collection.update_one.call_args.args[1], list)
    collection.find_one.assert_not_called()


def test_invalid_rating_does_not_access_db(monkeypatch):
    database = Mock()
    monkeypatch.setattr(app, 'get_database', database)
    assert not app.handle_rating('a', 'place', '99', '美食', '北區')
    database.assert_not_called()
