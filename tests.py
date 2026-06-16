#!/usr/bin/env python
from datetime import datetime, timezone, timedelta
import json
import unittest
from app import create_app, db
from app.models import User, Post
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    ELASTICSEARCH_URL = None
    REDIS_URL = 'redis://'
    SERVER_NAME = 'localhost'
    WTF_CSRF_ENABLED = False


class BaseTestCase(unittest.TestCase):
    """Base test case with app setup and helper methods."""

    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def create_user(self, username='john', email='john@example.com',
                    password='cat'):
        u = User(username=username, email=email)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u

    def get_token(self, username='john', password='cat'):
        response = self.client.post(
            '/api/tokens',
            headers={'Authorization': 'Basic ' +
                     self._basic_auth_header(username, password)})
        return response.get_json()['token']

    def _basic_auth_header(self, username, password):
        import base64
        credentials = base64.b64encode(
            f'{username}:{password}'.encode()).decode()
        return credentials

    def auth_headers(self, token):
        return {'Authorization': f'Bearer {token}'}

    def json_headers(self, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers


class UserModelCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_password_hashing(self):
        u = User(username='susan', email='susan@example.com')
        u.set_password('cat')
        self.assertFalse(u.check_password('dog'))
        self.assertTrue(u.check_password('cat'))

    def test_avatar(self):
        u = User(username='john', email='john@example.com')
        self.assertEqual(u.avatar(128), ('https://www.gravatar.com/avatar/'
                                         'd4c74594d841139328695756648b6bd6'
                                         '?d=identicon&s=128'))

    def test_follow(self):
        u1 = User(username='john', email='john@example.com')
        u2 = User(username='susan', email='susan@example.com')
        db.session.add(u1)
        db.session.add(u2)
        db.session.commit()
        following = db.session.scalars(u1.following.select()).all()
        followers = db.session.scalars(u2.followers.select()).all()
        self.assertEqual(following, [])
        self.assertEqual(followers, [])

        u1.follow(u2)
        db.session.commit()
        self.assertTrue(u1.is_following(u2))
        self.assertEqual(u1.following_count(), 1)
        self.assertEqual(u2.followers_count(), 1)
        u1_following = db.session.scalars(u1.following.select()).all()
        u2_followers = db.session.scalars(u2.followers.select()).all()
        self.assertEqual(u1_following[0].username, 'susan')
        self.assertEqual(u2_followers[0].username, 'john')

        u1.unfollow(u2)
        db.session.commit()
        self.assertFalse(u1.is_following(u2))
        self.assertEqual(u1.following_count(), 0)
        self.assertEqual(u2.followers_count(), 0)

    def test_follow_posts(self):
        # create four users
        u1 = User(username='john', email='john@example.com')
        u2 = User(username='susan', email='susan@example.com')
        u3 = User(username='mary', email='mary@example.com')
        u4 = User(username='david', email='david@example.com')
        db.session.add_all([u1, u2, u3, u4])

        # create four posts
        now = datetime.now(timezone.utc)
        p1 = Post(body="post from john", author=u1,
                  timestamp=now + timedelta(seconds=1))
        p2 = Post(body="post from susan", author=u2,
                  timestamp=now + timedelta(seconds=4))
        p3 = Post(body="post from mary", author=u3,
                  timestamp=now + timedelta(seconds=3))
        p4 = Post(body="post from david", author=u4,
                  timestamp=now + timedelta(seconds=2))
        db.session.add_all([p1, p2, p3, p4])
        db.session.commit()

        # setup the followers
        u1.follow(u2)  # john follows susan
        u1.follow(u4)  # john follows david
        u2.follow(u3)  # susan follows mary
        u3.follow(u4)  # mary follows david
        db.session.commit()

        # check the following posts of each user
        f1 = db.session.scalars(u1.following_posts()).all()
        f2 = db.session.scalars(u2.following_posts()).all()
        f3 = db.session.scalars(u3.following_posts()).all()
        f4 = db.session.scalars(u4.following_posts()).all()
        self.assertEqual(f1, [p2, p4, p1])
        self.assertEqual(f2, [p2, p3])
        self.assertEqual(f3, [p3, p4])
        self.assertEqual(f4, [p4])


class APICreateUserTestCase(BaseTestCase):
    """Tests for POST /api/users with various bad inputs."""

    def test_create_user_valid(self):
        """Successful user creation with valid data."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': 'alice',
                'email': 'alice@example.com',
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data['username'], 'alice')

    def test_create_user_no_json(self):
        """POST with no body / no Content-Type should not 500."""
        response = self.client.post('/api/users')
        self.assertIn(response.status_code, [400, 415])
        data = response.get_json()
        self.assertIn('error', data)

    def test_create_user_empty_json(self):
        """POST with empty JSON object should return 400."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({}),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)

    def test_create_user_error_has_readable_message(self):
        """Bad requests return a readable message, never a raw stack trace."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({}),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('message', data)
        self.assertIsInstance(data['message'], str)
        self.assertNotIn('Traceback', data['message'])

    def test_create_user_missing_password(self):
        """POST without password field should return 400."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': 'bob',
                'email': 'bob@example.com'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)

    def test_create_user_missing_email(self):
        """POST without email field should return 400."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': 'bob',
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)

    def test_create_user_missing_username(self):
        """POST without username field should return 400."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'email': 'bob@example.com',
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)

    def test_create_user_empty_username(self):
        """POST with empty string username should return 400."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': '',
                'email': 'bob@example.com',
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)

    def test_create_user_null_fields(self):
        """POST with null username/email should return 400."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': None,
                'email': None,
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)

    def test_create_user_integer_username(self):
        """POST with integer username should return 400."""
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': 123,
                'email': 'bob@example.com',
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)

    def test_create_user_wrong_content_type(self):
        """POST with text/plain Content-Type should return 400."""
        response = self.client.post(
            '/api/users',
            data='not json at all',
            headers={'Content-Type': 'text/plain'})
        self.assertEqual(response.status_code, 400)

    def test_create_user_invalid_json_body(self):
        """POST with malformed JSON should return 400."""
        response = self.client.post(
            '/api/users',
            data='{invalid json',
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)

    def test_create_user_duplicate_username(self):
        """POST with already existing username should return 400."""
        self.create_user()
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': 'john',
                'email': 'other@example.com',
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('username', data['message'])

    def test_create_user_duplicate_email(self):
        """POST with already existing email should return 400."""
        self.create_user()
        response = self.client.post(
            '/api/users',
            data=json.dumps({
                'username': 'other',
                'email': 'john@example.com',
                'password': 'dog'
            }),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('email', data['message'])


class APIUpdateUserTestCase(BaseTestCase):
    """Tests for PUT /api/users/<id> with various bad inputs."""

    def test_update_user_valid(self):
        """Successful user update with valid data."""
        user = self.create_user()
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user.id}',
            data=json.dumps({'about_me': 'Hello world'}),
            headers=self.json_headers(token))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['about_me'], 'Hello world')

    def test_update_user_no_json(self):
        """PUT with no body should not 500."""
        user = self.create_user()
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user.id}',
            headers=self.auth_headers(token))
        self.assertEqual(response.status_code, 400)

    def test_update_user_wrong_content_type(self):
        """PUT with wrong Content-Type should return 400."""
        user = self.create_user()
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user.id}',
            data='plain text',
            headers={'Content-Type': 'text/plain',
                     'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 400)

    def test_update_user_invalid_json(self):
        """PUT with malformed JSON should return 400."""
        user = self.create_user()
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user.id}',
            data='{bad json',
            headers=self.json_headers(token))
        self.assertEqual(response.status_code, 400)

    def test_update_user_empty_username(self):
        """PUT with empty username should return 400."""
        user = self.create_user()
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user.id}',
            data=json.dumps({'username': ''}),
            headers=self.json_headers(token))
        self.assertEqual(response.status_code, 400)

    def test_update_user_null_email(self):
        """PUT with null email should return 400."""
        user = self.create_user()
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user.id}',
            data=json.dumps({'email': None}),
            headers=self.json_headers(token))
        self.assertEqual(response.status_code, 400)

    def test_update_user_no_auth(self):
        """PUT without authentication should return 401."""
        user = self.create_user()
        response = self.client.put(
            f'/api/users/{user.id}',
            data=json.dumps({'about_me': 'test'}),
            headers=self.json_headers())
        self.assertEqual(response.status_code, 401)

    def test_update_user_wrong_user(self):
        """PUT for another user's id should return 403."""
        user1 = self.create_user()
        user2 = self.create_user(username='susan', email='susan@example.com')
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user2.id}',
            data=json.dumps({'about_me': 'hacked'}),
            headers=self.json_headers(token))
        self.assertEqual(response.status_code, 403)

    def test_update_user_wrong_user_bad_body(self):
        """Permission check wins over body validation: 403, not 400."""
        self.create_user()
        user2 = self.create_user(username='susan', email='susan@example.com')
        token = self.get_token()
        response = self.client.put(
            f'/api/users/{user2.id}',
            data='{bad json',
            headers=self.json_headers(token))
        self.assertEqual(response.status_code, 403)

    def test_update_user_duplicate_username(self):
        """PUT with username already taken by another user should return 400."""
        self.create_user()
        self.create_user(username='susan', email='susan@example.com')
        token = self.get_token()
        response = self.client.put(
            '/api/users/1',
            data=json.dumps({'username': 'susan'}),
            headers=self.json_headers(token))
        self.assertEqual(response.status_code, 400)


class APITranslateTestCase(BaseTestCase):
    """Tests for POST /translate with various bad inputs."""

    def _login(self):
        """Login via the auth/login form to get a session cookie."""
        self.create_user()
        # Use the test client to login via form
        self.client.post('/auth/login', data={
            'username': 'john',
            'password': 'cat',
        }, follow_redirects=True)

    def test_translate_no_json(self):
        """Translate with no body should return 400, not 500."""
        self._login()
        response = self.client.post('/translate')
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)

    def test_translate_empty_json(self):
        """Translate with empty JSON should return 400."""
        self._login()
        response = self.client.post(
            '/translate',
            data=json.dumps({}),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_translate_missing_text(self):
        """Translate without text field should return 400."""
        self._login()
        response = self.client.post(
            '/translate',
            data=json.dumps({
                'source_language': 'en',
                'dest_language': 'es'
            }),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_translate_missing_source_language(self):
        """Translate without source_language should return 400."""
        self._login()
        response = self.client.post(
            '/translate',
            data=json.dumps({
                'text': 'hello',
                'dest_language': 'es'
            }),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_translate_missing_dest_language(self):
        """Translate without dest_language should return 400."""
        self._login()
        response = self.client.post(
            '/translate',
            data=json.dumps({
                'text': 'hello',
                'source_language': 'en'
            }),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_translate_empty_text(self):
        """Translate with empty text string should return 400."""
        self._login()
        response = self.client.post(
            '/translate',
            data=json.dumps({
                'text': '',
                'source_language': 'en',
                'dest_language': 'es'
            }),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_translate_null_text(self):
        """Translate with null text should return 400."""
        self._login()
        response = self.client.post(
            '/translate',
            data=json.dumps({
                'text': None,
                'source_language': 'en',
                'dest_language': 'es'
            }),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_translate_wrong_content_type(self):
        """Translate with wrong Content-Type should return 400."""
        self._login()
        response = self.client.post(
            '/translate',
            data='not json',
            headers={'Content-Type': 'text/plain'})
        self.assertEqual(response.status_code, 400)

    def test_translate_error_has_readable_message(self):
        """Translate errors share the API's readable JSON error shape."""
        self._login()
        response = self.client.post(
            '/translate',
            data=json.dumps({'source_language': 'en', 'dest_language': 'es'}),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn('error', data)
        self.assertIn('message', data)
        self.assertIsInstance(data['message'], str)

    def test_translate_not_logged_in(self):
        """Translate without login should redirect (302) to login."""
        response = self.client.post(
            '/translate',
            data=json.dumps({
                'text': 'hello',
                'source_language': 'en',
                'dest_language': 'es'
            }),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 302)


class APISearchTestCase(BaseTestCase):
    """Tests for GET /search with edge cases."""

    def _login(self):
        self.create_user()
        self.client.post('/auth/login', data={
            'username': 'john',
            'password': 'cat',
        }, follow_redirects=True)

    def test_search_no_query(self):
        """Search without q parameter should redirect to explore."""
        self._login()
        response = self.client.get('/search')
        self.assertEqual(response.status_code, 302)

    def test_search_empty_query(self):
        """Search with empty q should redirect to explore."""
        self._login()
        response = self.client.get('/search?q=')
        self.assertEqual(response.status_code, 302)

    def test_search_whitespace_query(self):
        """Search with whitespace-only q should redirect to explore."""
        self._login()
        response = self.client.get('/search?q=%20%20%20')
        self.assertEqual(response.status_code, 302)

    def test_search_not_logged_in(self):
        """Search without login should redirect to login."""
        response = self.client.get('/search?q=test')
        self.assertEqual(response.status_code, 302)


class APIAuthTestCase(BaseTestCase):
    """Tests for auth-related API edge cases."""

    def test_get_token_no_auth(self):
        """POST /api/tokens without Basic auth should return 401."""
        response = self.client.post('/api/tokens')
        self.assertEqual(response.status_code, 401)

    def test_get_token_wrong_password(self):
        """POST /api/tokens with wrong credentials should return 401."""
        self.create_user()
        response = self.client.post(
            '/api/tokens',
            headers={'Authorization': 'Basic ' +
                     self._basic_auth_header('john', 'wrong')})
        self.assertEqual(response.status_code, 401)

    def test_get_user_no_token(self):
        """GET /api/users/1 without token should return 401."""
        user = self.create_user()
        response = self.client.get(f'/api/users/{user.id}')
        self.assertEqual(response.status_code, 401)

    def test_get_user_invalid_token(self):
        """GET /api/users/1 with invalid token should return 401."""
        user = self.create_user()
        response = self.client.get(
            f'/api/users/{user.id}',
            headers={'Authorization': 'Bearer invalidtoken123'})
        self.assertEqual(response.status_code, 401)

    def test_get_users_no_token(self):
        """GET /api/users without token should return 401."""
        response = self.client.get('/api/users')
        self.assertEqual(response.status_code, 401)

    def test_revoke_token_no_auth(self):
        """DELETE /api/tokens without token should return 401."""
        response = self.client.delete('/api/tokens')
        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main(verbosity=2)
