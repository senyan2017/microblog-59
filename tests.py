#!/usr/bin/env python
from datetime import datetime, timezone, timedelta
import unittest
import sqlalchemy as sa
from app import create_app, db
from app.main.pagination import paginate, paginate_search
from app.models import User, Post, Message
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    ELASTICSEARCH_URL = None


class ListPageTestConfig(TestConfig):
    # Small page size keeps the pagination fixtures tiny, and the list routes
    # are exercised over GET so CSRF protection is not needed here.
    POSTS_PER_PAGE = 3
    WTF_CSRF_ENABLED = False


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


class ListPageRoutesCase(unittest.TestCase):
    """Rendering and pagination behaviour of the shared list pages."""

    def setUp(self):
        self.app = create_app(ListPageTestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.user = User(username='john', email='john@example.com')
        self.user.set_password('cat')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login(self, user):
        # Log the user in without going through the form, so these tests stay
        # focused on the list pages rather than the auth flow.
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def make_posts(self, author, count):
        now = datetime.now(timezone.utc)
        for i in range(count):
            db.session.add(Post(body=f'post {i}', author=author,
                                timestamp=now + timedelta(seconds=i)))
        db.session.commit()

    def test_index_requires_login(self):
        response = self.client.get('/index')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.headers['Location'])

    def test_index_renders_posts(self):
        self.login(self.user)
        self.make_posts(self.user, 2)
        response = self.client.get('/index')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('post 0', html)
        self.assertIn('post 1', html)

    def test_index_pagination(self):
        self.login(self.user)
        self.make_posts(self.user, 5)  # POSTS_PER_PAGE is 3

        html1 = self.client.get('/index').get_data(as_text=True)
        self.assertIn('post 4', html1)  # newest post on page 1
        self.assertIn('post 2', html1)
        self.assertNotIn('post 1', html1)  # spills over to page 2
        self.assertIn('page=2', html1)  # "Older posts" link is live

        page2 = self.client.get('/index?page=2')
        self.assertEqual(page2.status_code, 200)
        html2 = page2.get_data(as_text=True)
        self.assertIn('post 1', html2)
        self.assertIn('post 0', html2)
        self.assertNotIn('post 4', html2)
        self.assertIn('page=1', html2)  # "Newer posts" link is live

    def test_explore_pagination(self):
        self.login(self.user)
        self.make_posts(self.user, 5)
        html1 = self.client.get('/explore').get_data(as_text=True)
        self.assertIn('page=2', html1)
        self.assertIn('page=1',
                      self.client.get('/explore?page=2').get_data(as_text=True))

    def test_user_page_pagination(self):
        self.login(self.user)
        self.make_posts(self.user, 5)
        page1 = self.client.get('/user/john')
        self.assertEqual(page1.status_code, 200)
        html1 = page1.get_data(as_text=True)
        self.assertIn('john', html1)
        self.assertIn('page=2', html1)
        self.assertIn(
            'page=1',
            self.client.get('/user/john?page=2').get_data(as_text=True))

    def test_messages_pagination(self):
        self.login(self.user)
        sender = User(username='susan', email='susan@example.com')
        db.session.add(sender)
        db.session.commit()
        now = datetime.now(timezone.utc)
        for i in range(5):
            db.session.add(Message(author=sender, recipient=self.user,
                                   body=f'msg {i}',
                                   timestamp=now + timedelta(seconds=i)))
        db.session.commit()

        page1 = self.client.get('/messages')
        self.assertEqual(page1.status_code, 200)
        html1 = page1.get_data(as_text=True)
        self.assertIn('msg 4', html1)
        self.assertIn('page=2', html1)  # real link, not the old dead '#'
        self.assertIn(
            'page=1',
            self.client.get('/messages?page=2').get_data(as_text=True))

    def test_search_renders(self):
        self.login(self.user)
        # Elasticsearch is disabled in tests, so search returns no results but
        # the page must still render.
        response = self.client.get('/search?q=test')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Search Results', response.get_data(as_text=True))

    def test_paginate_helper_builds_urls(self):
        self.make_posts(self.user, 5)
        query = sa.select(Post).order_by(Post.timestamp.desc())
        with self.app.test_request_context('/explore?page=1'):
            page = paginate(query, 'main.explore')
            self.assertEqual(len(page.items), 3)
            self.assertIsNone(page.prev_url)
            self.assertIn('page=2', page.next_url)
        with self.app.test_request_context('/explore?page=2'):
            page = paginate(query, 'main.explore')
            self.assertEqual(len(page.items), 2)
            self.assertIn('page=1', page.prev_url)
            self.assertIsNone(page.next_url)

    def test_paginate_search_helper_builds_urls(self):
        with self.app.test_request_context('/search?q=x&page=2'):
            page = paginate_search(['a', 'b', 'c'], total=10, page=2,
                                   endpoint='main.search', q='x')
            self.assertEqual(page.items, ['a', 'b', 'c'])
            self.assertIn('page=3', page.next_url)  # total 10 > 2 * 3
            self.assertIn('page=1', page.prev_url)
            self.assertIn('q=x', page.next_url)
        with self.app.test_request_context('/search?q=x&page=1'):
            page = paginate_search([], total=0, page=1,
                                   endpoint='main.search', q='x')
            self.assertIsNone(page.prev_url)
            self.assertIsNone(page.next_url)


if __name__ == '__main__':
    unittest.main(verbosity=2)
