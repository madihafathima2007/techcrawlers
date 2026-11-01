import os, re, json, base64, uuid, calendar as pycalendar
from email.utils import parseaddr
from email.header import decode_header, make_header
from html.parser import HTMLParser
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from email.mime.text import MIMEText

load_dotenv()

# Gmail OAuth scopes must match in both the authorization and callback flows.
GMAIL_SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
]

app = Flask(__name__)

database_url = os.getenv('DATABASE_URL', 'sqlite:///collab_os.db')

if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config.update(
    SECRET_KEY=os.getenv('SECRET_KEY', 'dev-only-change-this-secret-before-deploying'),
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to access your workspace.'



class EmailHTMLTextParser(HTMLParser):
    """Extract readable text from HTML email safely."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
        self.anchor_href = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag in ('script', 'style', 'head'):
            self.hidden += 1
        elif tag == 'a':
            self.anchor_href = attrs.get('href')
        elif tag in ('p', 'div', 'br', 'tr', 'li',
                     'h1', 'h2', 'h3', 'table'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden:
            self.hidden -= 1
        elif tag == 'a':
            self.anchor_href = None
        elif tag in ('p', 'div', 'tr', 'li', 'table'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.anchor_href and self.anchor_href.startswith(('http://', 'https://')):
                self.parts.append(f' ({self.anchor_href})')

    def get_text(self):
        text = ''.join(self.parts).replace('\r', '')
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()




def decode_gmail_body(payload):
    """Extract readable text from Gmail MIME messages."""
    plain_parts = []
    html_parts = []

    def walk(part):
        mime = part.get('mimeType', '').lower()
        data = part.get('body', {}).get('data')

        if data:
            try:
                raw = base64.urlsafe_b64decode(
                    data + '=' * (-len(data) % 4)
                )

                charset = 'utf-8'
                for header in part.get('headers', []):
                    if header.get('name', '').lower() == 'content-type':
                        m = re.search(
                            r'charset=["\']?([^;"\']+)',
                            header.get('value', ''),
                            re.I
                        )
                        if m:
                            charset = m.group(1).strip()

                decoded = raw.decode(charset, errors='replace').strip()

                if mime == 'text/plain' and decoded:
                    plain_parts.append(decoded)
                elif mime == 'text/html' and decoded:
                    html_parts.append(decoded)

            except Exception:
                app.logger.warning('Could not decode one Gmail body part.')

        for child in part.get('parts', []):
            walk(child)

    walk(payload or {})

    # Prefer actual readable plain text.
    body = '\n\n'.join(plain_parts).strip()

    # If plain text is only Gmail's HTML fallback, use the HTML alternative.
    if not body or 'open it in a program that understands HTML' in body.lower():
        if html_parts:
            parser = EmailHTMLTextParser()
            parser.feed('\n'.join(html_parts))
            body = parser.get_text()

    body = body.replace('\r\n', '\n').replace('\r', '\n')
    body = re.sub(r'[ \t]+', ' ', body)
    body = re.sub(r'\n{3,}', '\n\n', body)

    return body.strip()



class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    account_type = db.Column(db.String(20), nullable=False, default='individual')
    category = db.Column(db.String(100), default='')
    niche = db.Column(db.String(120), default='')
    primary_platform = db.Column(db.String(80), default='')
    social_handles = db.Column(db.String(500), default='')
    company_name = db.Column(db.String(180), default='')
    website = db.Column(db.String(255), default='')
    industry = db.Column(db.String(120), default='')
    company_size = db.Column(db.String(60), default='')
    auth_provider = db.Column(db.String(30), default='email')
    avatar_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Task(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),index=True)
    title=db.Column(db.String(220),nullable=False); description=db.Column(db.Text,default=''); status=db.Column(db.String(30),default='To do'); priority=db.Column(db.String(20),default='Medium'); due_date=db.Column(db.String(20),default=''); source=db.Column(db.String(100),default='Created manually'); collaboration_id=db.Column(db.Integer,db.ForeignKey('collaboration.id'),nullable=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Idea(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),index=True)
    title=db.Column(db.String(220),nullable=False); category=db.Column(db.String(80),default='Content'); notes=db.Column(db.Text,default=''); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Campaign(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),index=True)
    brand=db.Column(db.String(180),nullable=False); campaign=db.Column(db.String(220),nullable=False); platform=db.Column(db.String(80),default='Instagram'); deliverable=db.Column(db.String(220),default=''); fee=db.Column(db.String(80),default=''); deadline=db.Column(db.String(30),default=''); status=db.Column(db.String(30),default='Negotiating'); notes=db.Column(db.Text,default='')
class Email(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),index=True)
    gmail_id=db.Column(db.String(160),unique=True); sender=db.Column(db.String(220),default=''); subject=db.Column(db.String(300),default=''); snippet=db.Column(db.Text,default=''); received_at=db.Column(db.String(80),default=''); processed=db.Column(db.Boolean,default=False)


class EmailReplyDraft(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    email_id=db.Column(db.Integer,db.ForeignKey('email.id'),nullable=True,index=True)
    recipient=db.Column(db.String(255),default='')
    subject=db.Column(db.String(300),default='')
    body=db.Column(db.Text,nullable=False)
    status=db.Column(db.String(30),default='Draft')
    created_at=db.Column(db.DateTime,default=datetime.utcnow)

class ContentPost(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    title=db.Column(db.String(220),nullable=False); platform=db.Column(db.String(60),default='Instagram'); content_type=db.Column(db.String(60),default='Reel')
    scheduled_for=db.Column(db.String(30),default=''); status=db.Column(db.String(30),default='Idea'); caption=db.Column(db.Text,default=''); collaboration_id=db.Column(db.Integer,db.ForeignKey('collaboration.id'),nullable=True)
class FinanceEntry(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    entry_type=db.Column(db.String(20),default='Income'); category=db.Column(db.String(100),default='Other'); amount=db.Column(db.Float,default=0)
    description=db.Column(db.String(220),default=''); entry_date=db.Column(db.String(30),default='')
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.String(500), default='')
    category = db.Column(db.String(40), default='update')
    target_url = db.Column(db.String(300), default='')
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class SocialAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    platform = db.Column(db.String(40), nullable=False)
    handle = db.Column(db.String(120), nullable=False)
    profile_url = db.Column(db.String(300), default='')
    followers = db.Column(db.Integer, default=0)
    engagement_rate = db.Column(db.Float, default=0)
    notes = db.Column(db.String(300), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'platform', 'handle', name='unique_social_profile'),)

class Invitation(db.Model):
    id=db.Column(db.Integer,primary_key=True); company_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    creator_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True); message=db.Column(db.Text,default='')
    status=db.Column(db.String(30),default='Pending'); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    company=db.relationship('User',foreign_keys=[company_id]); creator=db.relationship('User',foreign_keys=[creator_id])
class CollaborationRequest(db.Model):
    id=db.Column(db.Integer,primary_key=True); creator_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    company_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True); message=db.Column(db.Text,default='')
    status=db.Column(db.String(30),default='Pending'); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    creator=db.relationship('User',foreign_keys=[creator_id]); company=db.relationship('User',foreign_keys=[company_id])

class DirectMessage(db.Model):
    id=db.Column(db.Integer,primary_key=True); sender_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    recipient_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True); body=db.Column(db.Text,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow); sender=db.relationship('User',foreign_keys=[sender_id]); recipient=db.relationship('User',foreign_keys=[recipient_id])

class Opportunity(db.Model):
    id=db.Column(db.Integer,primary_key=True); company_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    title=db.Column(db.String(220),nullable=False); description=db.Column(db.Text,default=''); platform=db.Column(db.String(80),default='Instagram')
    niche=db.Column(db.String(120),default=''); budget=db.Column(db.String(100),default=''); deadline=db.Column(db.String(30),default='')
    status=db.Column(db.String(30),default='Open'); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    company=db.relationship('User',foreign_keys=[company_id])

class Proposal(db.Model):
    id=db.Column(db.Integer,primary_key=True); opportunity_id=db.Column(db.Integer,db.ForeignKey('opportunity.id'),nullable=False,index=True)
    creator_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True); message=db.Column(db.Text,default='')
    proposed_fee=db.Column(db.String(100),default=''); status=db.Column(db.String(30),default='Pending'); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    opportunity=db.relationship('Opportunity',backref=db.backref('proposals',lazy=True,cascade='all, delete-orphan'))
    creator=db.relationship('User',foreign_keys=[creator_id])


class Collaboration(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    company_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    creator_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False,index=True)
    title=db.Column(db.String(220),nullable=False)
    agreed_amount=db.Column(db.Float,default=0)
    payment_due_date=db.Column(db.String(20),default='')
    payment_status=db.Column(db.String(30),default='Not paid')
    paid_date=db.Column(db.String(20),default='')
    status=db.Column(db.String(30),default='In progress')
    deadline=db.Column(db.String(20),default='')
    brief=db.Column(db.Text,default='')
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    completed_at=db.Column(db.DateTime,nullable=True)
    company=db.relationship('User',foreign_keys=[company_id])
    creator=db.relationship('User',foreign_keys=[creator_id])

class CollaborationDeliverable(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    collaboration_id=db.Column(db.Integer,db.ForeignKey('collaboration.id'),nullable=False,index=True)
    title=db.Column(db.String(220),nullable=False)
    due_date=db.Column(db.String(20),default='')
    notes=db.Column(db.Text,default='')
    status=db.Column(db.String(40),default='Not submitted')
    submission_url=db.Column(db.String(600),default='')
    created_at=db.Column(db.DateTime,default=datetime.utcnow)

class CollaborationReview(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    collaboration_id=db.Column(db.Integer,db.ForeignKey('collaboration.id'),nullable=False,index=True)
    reviewer_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
    reviewee_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
    rating=db.Column(db.Integer,nullable=False)
    payment_rating=db.Column(db.Integer,nullable=True)
    communication_rating=db.Column(db.Integer,nullable=True)
    comment=db.Column(db.Text,default='')
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    collaboration=db.relationship('Collaboration',backref=db.backref('reviews',lazy=True,cascade='all, delete-orphan'))
    reviewer=db.relationship('User',foreign_keys=[reviewer_id])
    reviewee=db.relationship('User',foreign_keys=[reviewee_id])
    __table_args__=(db.UniqueConstraint('collaboration_id','reviewer_id',name='unique_review_per_side'),)

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

@app.context_processor
def inject_globals():
    if current_user.is_authenticated:
        unread_notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        recent_notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
    else:
        unread_notifications, recent_notifications = 0, []
    return {'current_year': datetime.now().year, 'unread_notifications': unread_notifications,
            'recent_notifications': recent_notifications}

def create_notification(user_id, title, message='', category='update', target_url=''):
    db.session.add(Notification(user_id=user_id, title=title[:180], message=message[:500],
                                category=category[:40], target_url=target_url[:300]))


def account_required(kind):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.account_type != kind:
                flash('That workspace is not available for this account type.', 'error')
                return redirect(url_for('dashboard'))
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def extract_actions(text):
    """Rule-based suggestions from the text available in a synced email snippet."""
    clean=re.sub(r'\s+',' ',text or '').strip()
    sentences=re.split(r'(?<=[.!?])\s+|(?<=;)\s+',clean)
    cues=('please','can you','could you','need you to','send','share','submit','review','confirm','deliver','post','schedule','upload','prepare','complete','finish','provide','reply','respond','create','approve','by ')
    results=[]
    for sentence in sentences:
        s=sentence.strip(' -•')
        low=s.lower()
        if len(s)<18 or not any(c in low for c in cues):
            continue
        due=''
        # Recognise explicit ISO dates and common month/day forms; ambiguous dates remain blank.
        m=re.search(r'\b(20\d{2})-(0?[1-9]|1[0-2])-([0-2]?\d|3[01])\b',s)
        if m:
            try: due=datetime.strptime(m.group(0),'%Y-%m-%d').strftime('%Y-%m-%d')
            except ValueError: pass
        if not due:
            m=re.search(r'\b(?:deadline|by|before|due)\s*:?\s+(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?:\s+(20\d{2}))?\b',s,re.I)
            if not m:
                m=re.search(r'\b(?:deadline|by|before|due)\s*:?\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b',s,re.I)
            if m:
                try:
                    if m.lastindex and m.group(1).isdigit(): day,month,year=m.group(1),m.group(2),m.group(3)
                    else: month,day,year=m.group(1),m.group(2),m.group(3)
                    year=int(year or datetime.now().year)
                    due=datetime.strptime(f'{day} {month} {year}','%d %B %Y').strftime('%Y-%m-%d')
                except ValueError:
                    try: due=datetime.strptime(f'{day} {month[:3]} {year}','%d %b %Y').strftime('%Y-%m-%d')
                    except Exception: due=''
        priority='High' if any(w in low for w in ('urgent','asap','immediately','high priority','as soon as possible')) else ('Low' if any(w in low for w in ('when convenient','no rush','whenever possible')) else 'Medium')
        title=s[:115]+('…' if len(s)>115 else '')
        if not any(x['title']==title for x in results):
            results.append({'title':title,'description':'Suggested from an email. Check the original message and confirm the exact deliverable and deadline.','due_date':due,'priority':priority})
    return results[:5]

@app.get('/')
def landing():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET','POST'])
def signup():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method=='POST':
        d=request.form; account_type=d.get('account_type','individual')
        name=d.get('name','').strip(); email=d.get('email','').strip().lower(); password=d.get('password','')
        if account_type not in ('individual','company'): flash('Choose an account type.', 'error')
        elif not name or not email or len(password)<8: flash('Enter your name, a valid email and a password of at least 8 characters.', 'error')
        elif User.query.filter_by(email=email).first(): flash('An account with this email already exists. Please sign in.', 'error')
        elif account_type=='company' and not d.get('company_name','').strip(): flash('Company name is required.', 'error')
        else:
            user=User(name=name,email=email,password_hash=generate_password_hash(password),account_type=account_type,
                category=d.get('category',''),niche=d.get('niche',''),primary_platform=d.get('primary_platform',''),social_handles=d.get('social_handles',''),
                company_name=d.get('company_name',''),website=d.get('website',''),industry=d.get('industry',''),company_size=d.get('company_size',''))
            db.session.add(user); db.session.commit(); login_user(user); flash('Your workspace is ready. Welcome to CreatorOS!', 'success'); return redirect(url_for('dashboard'))
    return render_template('auth.html', mode='signup')

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        user=User.query.filter_by(email=email).first()
        if user and user.password_hash and check_password_hash(user.password_hash,password):
            login_user(user, remember=bool(request.form.get('remember'))); return redirect(url_for('dashboard'))
        flash('Email or password is incorrect.', 'error')
    return render_template('auth.html', mode='login')

@app.get('/switch-account')
@login_required
def switch_account():
    # Switching accounts always returns to authentication; it never exposes another account session.
    logout_user()
    session.clear()
    flash('Signed out. Sign in with the other account to switch workspaces.', 'success')
    return redirect(url_for('login'))

@app.get('/logout')
@login_required
def logout(): logout_user(); flash('You have been signed out.', 'success'); return redirect(url_for('login'))

@app.get('/forgot-password')
def forgot_password():
    flash('Password reset email delivery is not configured in this local prototype. Contact your workspace administrator or create a new test account.', 'error')
    return redirect(url_for('login'))

@app.get('/auth/<provider>')
def oauth_login(provider):
    if provider not in ('google','linkedin'): return redirect(url_for('login'))
    client_id=os.getenv(f'{provider.upper()}_CLIENT_ID'); client_secret=os.getenv(f'{provider.upper()}_CLIENT_SECRET')
    if not client_id or not client_secret:
        flash(f'{provider.title()} sign-in is not configured yet. Add its OAuth credentials to your .env file.', 'error'); return redirect(url_for('login'))
    try:
        from authlib.integrations.flask_client import OAuth
        oauth=OAuth(app)
        if provider=='google':
            client=oauth.register(name='google',client_id=client_id,client_secret=client_secret,server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',client_kwargs={'scope':'openid email profile'})
        else:
            client=oauth.register(name='linkedin',client_id=client_id,client_secret=client_secret,server_metadata_url='https://www.linkedin.com/oauth/.well-known/openid-configuration',client_kwargs={'scope':'openid profile email'})
        session['oauth_provider']=provider
        return client.authorize_redirect(url_for('oauth_callback',provider=provider,_external=True))
    except Exception:
        app.logger.exception('OAuth initialization failed')
        flash('Could not start social sign-in. Check OAuth settings and the Authlib installation.', 'error'); return redirect(url_for('login'))

@app.get('/auth/<provider>/callback')
def oauth_callback(provider):
    try:
        from authlib.integrations.flask_client import OAuth
        oauth=OAuth(app); client_id=os.getenv(f'{provider.upper()}_CLIENT_ID'); client_secret=os.getenv(f'{provider.upper()}_CLIENT_SECRET')
        if provider=='google': client=oauth.register(name='google',client_id=client_id,client_secret=client_secret,server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',client_kwargs={'scope':'openid email profile'})
        else: client=oauth.register(name='linkedin',client_id=client_id,client_secret=client_secret,server_metadata_url='https://www.linkedin.com/oauth/.well-known/openid-configuration',client_kwargs={'scope':'openid profile email'})
        token=client.authorize_access_token(); info=token.get('userinfo') or client.userinfo()
        email=(info.get('email') or '').lower(); name=info.get('name') or info.get('given_name') or email.split('@')[0]
        if not email: flash('The provider did not share an email address. Use email sign-up instead.', 'error'); return redirect(url_for('signup'))
        user=User.query.filter_by(email=email).first()
        if not user:
            session['pending_social']={'email':email,'name':name,'provider':provider}
            return redirect(url_for('social_complete'))
        login_user(user); return redirect(url_for('dashboard'))
    except Exception:
        app.logger.exception('OAuth callback failed'); flash('Social sign-in could not be completed. Please try again.', 'error'); return redirect(url_for('login'))

@app.route('/social/complete',methods=['GET','POST'])
def social_complete():
    pending=session.get('pending_social')
    if not pending: return redirect(url_for('signup'))
    if request.method=='POST':
        d=request.form; kind=d.get('account_type','individual')
        if kind not in ('individual','company') or (kind=='company' and not d.get('company_name','').strip()): flash('Complete the required account details.', 'error')
        else:
            user=User(name=pending['name'],email=pending['email'],account_type=kind,auth_provider=pending['provider'],category=d.get('category',''),niche=d.get('niche',''),primary_platform=d.get('primary_platform',''),social_handles=d.get('social_handles',''),company_name=d.get('company_name',''),website=d.get('website',''),industry=d.get('industry',''),company_size=d.get('company_size',''))
            db.session.add(user); db.session.commit(); session.pop('pending_social',None); login_user(user); return redirect(url_for('dashboard'))
    return render_template('auth.html',mode='social',social_name=pending['name'],social_email=pending['email'])

@app.get('/dashboard')
@login_required
def dashboard():
    uid=current_user.id
    tasks=Task.query.filter_by(user_id=uid).order_by(Task.created_at.desc()).limit(8).all()
    ideas=Idea.query.filter_by(user_id=uid).order_by(Idea.created_at.desc()).limit(4).all()
    campaigns=Campaign.query.filter_by(user_id=uid).order_by(Campaign.id.desc()).limit(4).all()
    stats={'tasks':Task.query.filter_by(user_id=uid,status='To do').count(),'ideas':Idea.query.filter_by(user_id=uid).count(),'campaigns':Campaign.query.filter_by(user_id=uid).count(),'emails':Email.query.filter_by(user_id=uid).count(),'posts':ContentPost.query.filter_by(user_id=uid).count(),'income':sum(x.amount for x in FinanceEntry.query.filter_by(user_id=uid,entry_type='Income').all())}
    if current_user.account_type=='company':
        active_deals=Collaboration.query.filter_by(company_id=uid).filter(Collaboration.status!='Completed').order_by(Collaboration.created_at.desc()).limit(6).all()
        opportunities=Opportunity.query.filter_by(company_id=uid).order_by(Opportunity.created_at.desc()).limit(5).all()
        pending=Proposal.query.join(Opportunity).filter(Opportunity.company_id==uid,Proposal.status=='Pending').order_by(Proposal.created_at.desc()).limit(6).all()
        stats.update(active_deals=Collaboration.query.filter_by(company_id=uid).filter(Collaboration.status!='Completed').count(),open_campaigns=Opportunity.query.filter_by(company_id=uid,status='Open').count(),pending_proposals=Proposal.query.join(Opportunity).filter(Opportunity.company_id==uid,Proposal.status=='Pending').count(),awaiting_approval=CollaborationDeliverable.query.join(Collaboration).filter(Collaboration.company_id==uid,CollaborationDeliverable.status=='Submitted').count(),committed_budget=sum(x.agreed_amount or 0 for x in Collaboration.query.filter_by(company_id=uid).all()))
        return render_template('company_dashboard.html',tasks=tasks,campaigns=campaigns,stats=stats,active_deals=active_deals,opportunities=opportunities,pending=pending)
    return render_template('index.html',tasks=tasks,ideas=ideas,campaigns=campaigns,stats=stats)

@app.get('/tasks')
@login_required
def tasks_page(): return render_template('tasks.html',tasks=Task.query.filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).all())
@app.get('/ideas')
@account_required('individual')
def ideas_page(): return render_template('ideas.html',ideas=Idea.query.filter_by(user_id=current_user.id).order_by(Idea.created_at.desc()).all())
@app.get('/campaigns')
@login_required
def campaigns_page(): return render_template('campaigns.html',campaigns=Campaign.query.filter_by(user_id=current_user.id).order_by(Campaign.id.desc()).all())
@app.get('/inbox')
@login_required
def inbox_page():
    token_path = f'gmail-token-{current_user.id}.json'
    return render_template(
        'inbox.html',
        emails=Email.query.filter_by(user_id=current_user.id).order_by(Email.id.desc()).all(),
        gmail_ready=bool(os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET')),
        gmail_connected=os.path.exists(token_path),
        reply_drafts=EmailReplyDraft.query.filter_by(user_id=current_user.id).order_by(EmailReplyDraft.id.desc()).limit(10).all(),
    )

@app.post('/gmail/sync')
@login_required
def gmail_sync():
    """Fetch recent Gmail messages for the signed-in COLLAB user."""
    token_path = f'gmail-token-{current_user.id}.json'
    if not os.path.exists(token_path):
        flash('Connect Gmail before syncing messages.', 'error')
        return redirect(url_for('inbox_page'))

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(token_path, scopes=GMAIL_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            with open(token_path, 'w', encoding='utf-8') as token_file:
                token_file.write(creds.to_json())
        if not creds.valid:
            raise RuntimeError('The Gmail authorization has expired. Please reconnect Gmail.')

        service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
        result = service.users().messages().list(userId='me', maxResults=30).execute()
        messages = result.get('messages', [])
        added = 0
        updated = 0
        for item in messages:
            msg = service.users().messages().get(
                userId='me', id=item['id'], format='full'
            ).execute()
            def inspect_mime(part, depth=0):
                print(
                    "  " * depth,
                    "MIME:", part.get('mimeType'),
                    "| BODY SIZE:", part.get('body', {}).get('size', 0),
                    "| HAS DATA:", bool(part.get('body', {}).get('data'))
                )
                for child in part.get('parts', []):
                    inspect_mime(child, depth + 1)

            print("\n--- COLLAB GMAIL MIME DEBUG ---")
            inspect_mime(msg.get('payload', {}))
            print("--- END MIME DEBUG ---\n")

            headers = {h.get('name', '').lower(): h.get('value', '')
                       for h in msg.get('payload', {}).get('headers', [])}
            existing = Email.query.filter_by(gmail_id=item['id'], user_id=current_user.id).first()
            # gmail_id is unique in this prototype; don't attach another user's message.
            if existing is None and Email.query.filter_by(gmail_id=item['id']).first():
                continue
            received_ms = msg.get('internalDate')
            received_at = datetime.utcfromtimestamp(int(received_ms) / 1000).strftime('%Y-%m-%d %H:%M UTC') if received_ms else headers.get('date', '')
            if existing is None:
                existing = Email(user_id=current_user.id, gmail_id=item['id'])
                db.session.add(existing)
                added += 1
            else:
                updated += 1
            existing.sender = headers.get('from', 'Unknown sender')[:220]
            existing.subject = headers.get('subject', '(No subject)')[:300]
            decoded_body = decode_gmail_body(msg.get('payload', {}))
            print("DECODED BODY LENGTH:", len(decoded_body))
            print("DECODED BODY PREVIEW:", repr(decoded_body[:200]))

            existing.snippet = decoded_body or msg.get('snippet', '')
            existing.received_at = received_at
        db.session.commit()
        flash(f'Gmail sync complete: {added} new messages, {updated} refreshed. Google returned {len(messages)} recent messages.', 'success')
    except Exception as exc:
        db.session.rollback()
        app.logger.exception('Gmail message sync failed')
        flash(f'Gmail sync failed: {type(exc).__name__}: {exc}', 'error')
    return redirect(url_for('inbox_page'))

@app.post('/api/tasks')
@login_required
def add_task():
    d=request.get_json(silent=True) or request.form
    if not d.get('title'): return jsonify(error='A task title is required'),400
    item=Task(user_id=current_user.id,title=d['title'],description=d.get('description',''),priority=d.get('priority','Medium'),due_date=d.get('due_date',''),source=d.get('source','Created manually'))
    db.session.add(item); create_notification(current_user.id, 'Task created', f'{item.title} was added to your task list.', 'task', url_for('tasks_page')); db.session.commit(); return jsonify(id=item.id,title=item.title)
@app.patch('/api/tasks/<int:item_id>')
@login_required
def update_task(item_id):
    item=Task.query.filter_by(id=item_id,user_id=current_user.id).first_or_404(); d=request.get_json() or {}
    for key in ('status','priority','due_date','title','description'):
        if key in d: setattr(item,key,d[key])
    db.session.commit(); return jsonify(ok=True)
@app.delete('/api/tasks/<int:item_id>')
@login_required
def delete_task(item_id):
    item=Task.query.filter_by(id=item_id,user_id=current_user.id).first_or_404(); db.session.delete(item); db.session.commit(); return jsonify(ok=True)
@app.post('/api/ideas')
@account_required('individual')
def add_idea():
    d=request.get_json(silent=True) or request.form
    if not d.get('title'): return jsonify(error='An idea title is required'),400
    item=Idea(user_id=current_user.id,title=d['title'],category=d.get('category','Content'),notes=d.get('notes','')); db.session.add(item); db.session.commit(); return jsonify(id=item.id)
@app.delete('/api/ideas/<int:item_id>')
@account_required('individual')
def delete_idea(item_id):
    item=Idea.query.filter_by(id=item_id,user_id=current_user.id).first_or_404(); db.session.delete(item); db.session.commit(); return jsonify(ok=True)
@app.post('/api/campaigns')
@login_required
def add_campaign():
    d=request.get_json(silent=True) or request.form
    if not d.get('brand') or not d.get('campaign'): return jsonify(error='Brand and campaign name are required'),400
    item=Campaign(user_id=current_user.id,brand=d['brand'],campaign=d['campaign'],platform=d.get('platform','Instagram'),deliverable=d.get('deliverable',''),fee=d.get('fee',''),deadline=d.get('deadline',''),status=d.get('status','Negotiating'),notes=d.get('notes','')); db.session.add(item); db.session.commit(); return jsonify(id=item.id)
@app.delete('/api/campaigns/<int:item_id>')
@login_required
def delete_campaign(item_id):
    item=Campaign.query.filter_by(id=item_id,user_id=current_user.id).first_or_404(); db.session.delete(item); db.session.commit(); return jsonify(ok=True)
@app.post('/api/ideas/generate')
@account_required('individual')
def generate_ideas():
    d=request.get_json() or {}; niche=d.get('niche') or current_user.niche or 'your niche'; audience=d.get('audience','your audience')
    suggestions=[(f'A day in the life of a {niche} creator','Short-form video','Show the real workflow, one challenge, and one useful takeaway for '+audience+'.'),(f'3 mistakes people make with {niche}','Educational carousel','A save-worthy breakdown with a strong hook and practical fixes.'),(f'Myth vs fact: {niche}','Community','Ask followers to vote, then explain the surprising answer.'),(f'Behind the scenes: how I make a {niche} post','Behind the scenes','Capture the idea, setup, editing and final result.'),(f'A 7-day challenge for {audience}','Series','Invite the community to participate and share progress.')]
    made=[]
    for title,cat,notes in suggestions:
        db.session.add(Idea(user_id=current_user.id,title=title,category=cat,notes=notes)); made.append(title)
    db.session.commit(); return jsonify(ideas=made)
@app.get('/gmail/actions/<int:email_id>')
@login_required
def gmail_email_actions(email_id):
    item=Email.query.filter_by(id=email_id,user_id=current_user.id).first_or_404()
    return jsonify(actions=extract_actions(f"{item.subject or ''}. {item.snippet or ''}"), email_subject=item.subject or '(No subject)')

@app.post('/gmail/process/<int:email_id>')
@login_required
def gmail_process_email(email_id):
    item=Email.query.filter_by(id=email_id,user_id=current_user.id).first_or_404()
    actions=extract_actions(f"{item.subject or ''}. {item.snippet or ''}")
    data=request.get_json(silent=True) or {}
    approved=data.get('approved',[])
    if not isinstance(approved,list): return jsonify(error='Invalid task selection.'),400
    created=[]
    for index in approved:
        if not isinstance(index,int) or index<0 or index>=len(actions): continue
        action=actions[index]
        existing=Task.query.filter_by(user_id=current_user.id,title=action['title']).first()
        if existing: continue
        task=Task(user_id=current_user.id,title=action['title'],description=action['description'],priority=action['priority'],due_date=action['due_date'],source='Gmail suggestion')
        db.session.add(task); created.append(action['title'])
    item.processed=True
    db.session.commit()
    return jsonify(created=created, total=len(actions))

@app.post('/api/email-suggestions')
@login_required
def email_suggestions():
    d=request.get_json() or {}; actions=extract_actions(d.get('text','')); created=[]
    for title in actions:
        if not Task.query.filter_by(user_id=current_user.id,title=title).first(): db.session.add(Task(user_id=current_user.id,title=title,description='Suggested from an email. Verify details and deadline.',priority='Medium',source='Email suggestion')); created.append(title)
    db.session.commit(); return jsonify(suggestions=actions,created=created)
def build_reply_draft(sender, subject, message, user_name):
    text=(message or '').lower()
    if any(k in text for k in ('payment overdue','payment delayed','payment pending','invoice')):
        body=f"Hi,\n\nThank you for the update. I wanted to follow up on the payment related to this collaboration. Could you please confirm the current status and the expected payment date?\n\nI would appreciate an update so we can keep everything on track.\n\nBest,\n{user_name}"
    elif any(k in text for k in ('collaboration','campaign','partnership','brand deal','proposal')):
        body=f"Hi,\n\nThank you for reaching out and considering me for this opportunity. I'd be happy to learn more about the campaign, including the deliverables, timeline, usage requirements and budget.\n\nLooking forward to hearing more.\n\nBest,\n{user_name}"
    elif any(k in text for k in ('meeting','call','schedule','available')):
        body=f"Hi,\n\nThanks for your message. I'd be happy to discuss this further. Please share a couple of suitable time slots and I'll confirm what works for me.\n\nBest,\n{user_name}"
    elif any(k in text for k in ('feedback','revision','changes','edit')):
        body=f"Hi,\n\nThanks for sharing your feedback. I've received your notes and will review the requested changes. If anything needs clarification, I'll get back to you before proceeding.\n\nBest,\n{user_name}"
    else:
        body=f"Hi,\n\nThank you for your email. I've received your message and will review the details. I'll get back to you shortly with an update.\n\nBest,\n{user_name}"
    return body

@app.post('/api/email-reply/manual')
@login_required
def draft_manual_email_reply():
    d=request.get_json(silent=True) or {}
    message=(d.get('message') or '').strip()
    if not message: return jsonify(error='Paste the email message first.'),400
    recipient=(d.get('recipient') or '').strip()
    subject=(d.get('subject') or '').strip()
    body=build_reply_draft(recipient,subject,message,current_user.name)
    draft=EmailReplyDraft(user_id=current_user.id,recipient=recipient,subject=('Re: '+subject if subject and not subject.lower().startswith('re:') else subject),body=body)
    db.session.add(draft); db.session.commit()
    return jsonify(id=draft.id,recipient=draft.recipient,subject=draft.subject,body=draft.body,status=draft.status,send_ready=False)

@app.post('/api/email-reply/<int:email_id>')
@login_required
def draft_email_reply(email_id):
    email=Email.query.filter_by(id=email_id,user_id=current_user.id).first_or_404()
    body=build_reply_draft(email.sender,email.subject,email.snippet,current_user.name)
    draft=EmailReplyDraft(user_id=current_user.id,email_id=email.id,recipient=email.sender,subject=('Re: '+email.subject if email.subject and not email.subject.lower().startswith('re:') else email.subject),body=body)
    db.session.add(draft); db.session.commit()
    return jsonify(id=draft.id,recipient=draft.recipient,subject=draft.subject,body=draft.body,status=draft.status,send_ready=bool(email.gmail_id))

@app.patch('/api/email-reply/<int:draft_id>')
@login_required
def update_email_reply_draft(draft_id):
    draft=EmailReplyDraft.query.filter_by(id=draft_id,user_id=current_user.id,status='Draft').first_or_404()
    d=request.get_json(silent=True) or {}
    recipient=(d.get('recipient') or '').strip()
    if recipient and ('@' not in parseaddr(recipient)[1] or '.' not in parseaddr(recipient)[1].split('@')[-1]): return jsonify(error='Enter a valid recipient email address.'),400
    draft.recipient=recipient
    draft.subject=(d.get('subject') or '').strip()[:300]
    draft.body=(d.get('body') or '').strip()
    if not draft.body: return jsonify(error='Reply message cannot be empty.'),400
    db.session.commit()
    return jsonify(ok=True)

@app.post('/api/email-reply/<int:draft_id>/send')
@login_required
def approve_and_send_email_reply(draft_id):
    draft=EmailReplyDraft.query.filter_by(id=draft_id,user_id=current_user.id,status='Draft').first_or_404()
    if not draft.email_id:
        return jsonify(error='This is a manual draft. Copy it into your email app to send.'),400
    email=Email.query.filter_by(id=draft.email_id,user_id=current_user.id).first_or_404()
    token_path=f'gmail-token-{current_user.id}.json'
    if not os.path.exists(token_path): return jsonify(error='Connect Gmail with sending permission before sending.'),400
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        with open(token_path) as f: token_data=json.load(f)
        creds=Credentials.from_authorized_user_info(token_data,scopes=GMAIL_SCOPES)
        if not creds.has_scopes(['https://www.googleapis.com/auth/gmail.send']):
            return jsonify(error='Gmail sending permission is not granted. Reconnect Gmail and approve the send permission.'),403
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path,'w') as f: json.dump(json.loads(creds.to_json()),f)
        msg=MIMEText(draft.body)
        msg['to']=draft.recipient
        msg['subject']=draft.subject
        raw=base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service=build('gmail','v1',credentials=creds,cache_discovery=False)
        service.users().messages().send(userId='me',body={'raw':raw}).execute()
        draft.status='Sent'; db.session.commit()
        return jsonify(ok=True,status='Sent')
    except Exception as exc:
        app.logger.exception('Approved Gmail reply failed')
        return jsonify(error='Gmail could not send this reply. Check the connection and try again.'),502

def create_collaboration(company_id, creator_id, title, amount_text='', deadline=''):
    existing=Collaboration.query.filter_by(company_id=company_id,creator_id=creator_id,title=title).first()
    if existing:
        if deadline and not existing.deadline: existing.deadline=deadline
        return existing
    import re as _re
    raw=str(amount_text or '')
    nums=_re.sub(r'[^0-9.]','',raw)
    amount=float(nums) if nums else 0
    item=Collaboration(company_id=company_id,creator_id=creator_id,title=title,agreed_amount=amount,deadline=deadline or '')
    db.session.add(item)
    db.session.flush()
    if deadline:
        sync_collaboration_deadline(item)
    create_notification(creator_id, 'New brand partnership', f'{title} was accepted. Open your Brand Deal Room to review the brief and deadline.', 'partnership', url_for('deal_room', collab_id=item.id))
    create_notification(company_id, 'Partnership created', f'{title} is now active. Add the campaign brief and deliverables in the Brand Deal Room.', 'partnership', url_for('deal_room', collab_id=item.id))
    return item

def sync_collaboration_deadline(deal):
    """Keep one creator task and one creator calendar item in sync with the company deadline."""
    if not deal.deadline:
        return
    task=Task.query.filter_by(user_id=deal.creator_id,collaboration_id=deal.id).first()
    task_title=f'Submit deliverables: {deal.title}'
    if not task:
        task=Task(user_id=deal.creator_id,collaboration_id=deal.id,title=task_title,description='Automatically created from the company deadline in your Brand Deal Room.',status='To do',priority='High',due_date=deal.deadline,source='Brand partnership')
        db.session.add(task)
    else:
        task.title=task_title; task.due_date=deal.deadline; task.description='Automatically updated from the company deadline in your Brand Deal Room.'
    post=ContentPost.query.filter_by(user_id=deal.creator_id,collaboration_id=deal.id).first()
    if not post:
        post=ContentPost(user_id=deal.creator_id,collaboration_id=deal.id,title=f'Campaign deliverables: {deal.title}',platform='Other',content_type='Brand deliverables',scheduled_for=deal.deadline,status='Draft',caption='Automatically created from the company deadline. See your Brand Deal Room for the brief.')
        db.session.add(post)
    else:
        post.scheduled_for=deal.deadline
    create_notification(deal.creator_id,'Partnership deadline added',f'{deal.title} is due on {deal.deadline}. A task and calendar entry have been added.', 'task', url_for('deal_room',collab_id=deal.id))

@app.get('/marketplace')
@login_required
def marketplace():
    if current_user.account_type=='company':
        creators=User.query.filter_by(account_type='individual').order_by(User.created_at.desc()).all()
        incoming=Proposal.query.join(Opportunity).filter(Opportunity.company_id==current_user.id).order_by(Proposal.created_at.desc()).all()
        opportunities=Opportunity.query.filter_by(company_id=current_user.id).order_by(Opportunity.created_at.desc()).all()
        invitations=Invitation.query.filter_by(company_id=current_user.id).order_by(Invitation.created_at.desc()).all()
        creator_requests=CollaborationRequest.query.filter_by(company_id=current_user.id).order_by(CollaborationRequest.created_at.desc()).all()
        return render_template('marketplace.html',mode='company',creators=creators,incoming=incoming,opportunities=opportunities,invitations=invitations,creator_requests=creator_requests)
    opportunities=Opportunity.query.filter_by(status='Open').order_by(Opportunity.created_at.desc()).all()
    sent=Proposal.query.filter_by(creator_id=current_user.id).order_by(Proposal.created_at.desc()).all()
    invitations=Invitation.query.filter_by(creator_id=current_user.id).order_by(Invitation.created_at.desc()).all()
    companies=User.query.filter_by(account_type='company').order_by(User.created_at.desc()).all()
    outgoing_requests=CollaborationRequest.query.filter_by(creator_id=current_user.id).order_by(CollaborationRequest.created_at.desc()).all()
    return render_template('marketplace.html',mode='individual',opportunities=opportunities,sent=sent,invitations=invitations,companies=companies,outgoing_requests=outgoing_requests)

@app.post('/marketplace/opportunities')
@account_required('company')
def create_opportunity():
    d=request.form; title=d.get('title','').strip()
    if not title: flash('Add a campaign title before publishing.','error')
    else:
        db.session.add(Opportunity(company_id=current_user.id,title=title,description=d.get('description','').strip(),platform=d.get('platform','Instagram'),niche=d.get('niche','').strip(),budget=d.get('budget','').strip(),deadline=d.get('deadline','')))
        db.session.commit(); flash('Opportunity published to the marketplace.','success')
    return redirect(url_for('marketplace'))

@app.post('/marketplace/opportunities/<int:opportunity_id>/apply')
@account_required('individual')
def apply_opportunity(opportunity_id):
    item=Opportunity.query.filter_by(id=opportunity_id,status='Open').first_or_404()
    if Proposal.query.filter_by(opportunity_id=item.id,creator_id=current_user.id).first(): flash('You have already sent a proposal.','error')
    else:
        db.session.add(Proposal(opportunity_id=item.id,creator_id=current_user.id,message=request.form.get('message','').strip(),proposed_fee=request.form.get('proposed_fee','').strip()))
        db.session.commit(); flash('Proposal sent to the company.','success')
    return redirect(url_for('marketplace'))

@app.post('/marketplace/proposals/<int:proposal_id>/<action>')
@account_required('company')
def update_proposal(proposal_id,action):
    p=Proposal.query.join(Opportunity).filter(Proposal.id==proposal_id,Opportunity.company_id==current_user.id).first_or_404()
    if action not in ('accept','decline'): return 'Invalid action',400
    p.status='Accepted' if action=='accept' else 'Declined'
    if action=='accept': create_collaboration(p.opportunity.company_id,p.creator_id,p.opportunity.title,p.proposed_fee or p.opportunity.budget,p.opportunity.deadline)
    db.session.commit(); flash('Proposal '+p.status.lower()+'.','success')
    return redirect(url_for('marketplace'))


@app.post('/marketplace/company-request/<int:company_id>')
@account_required('individual')
def request_company_collaboration(company_id):
    company=User.query.filter_by(id=company_id,account_type='company').first_or_404()
    existing=CollaborationRequest.query.filter_by(creator_id=current_user.id,company_id=company.id,status='Pending').first()
    if existing:
        flash('You already have a pending request with this company.','error')
    else:
        message=request.form.get('message','').strip()
        if not message:
            flash('Add a short message explaining why you want to collaborate.','error')
        else:
            db.session.add(CollaborationRequest(creator_id=current_user.id,company_id=company.id,message=message))
            db.session.commit(); flash('Collaboration request sent to the company.','success')
    return redirect(url_for('marketplace'))

@app.post('/marketplace/company-requests/<int:request_id>/<action>')
@account_required('company')
def update_company_request(request_id,action):
    item=CollaborationRequest.query.filter_by(id=request_id,company_id=current_user.id).first_or_404()
    if action not in ('accept','decline'): return 'Invalid action',400
    item.status='Accepted' if action=='accept' else 'Declined'
    if action=='accept': create_collaboration(item.company_id,item.creator_id,'Direct collaboration request')
    db.session.commit(); flash('Creator request '+item.status.lower()+'.','success')
    return redirect(url_for('marketplace'))

@app.get('/deals/<int:collab_id>')
@login_required
def deal_room(collab_id):
    deal=Collaboration.query.filter(Collaboration.id==collab_id,((Collaboration.company_id==current_user.id)|(Collaboration.creator_id==current_user.id))).first_or_404()
    deliverables=CollaborationDeliverable.query.filter_by(collaboration_id=deal.id).order_by(CollaborationDeliverable.due_date.asc(),CollaborationDeliverable.id.asc()).all()
    return render_template('deal_room.html',deal=deal,deliverables=deliverables)

@app.post('/deals/<int:collab_id>/update')
@account_required('company')
def deal_room_update(collab_id):
    deal=Collaboration.query.filter_by(id=collab_id,company_id=current_user.id).first_or_404()
    d=request.form
    deadline=(d.get('deadline') or '').strip()
    if deadline:
        try: datetime.strptime(deadline,'%Y-%m-%d')
        except ValueError: flash('Choose a valid campaign deadline.','error'); return redirect(url_for('deal_room',collab_id=deal.id))
    try: amount=max(0,float(d.get('amount') or 0))
    except ValueError: amount=deal.agreed_amount or 0
    deal.title=(d.get('title') or deal.title).strip()[:220]
    deal.agreed_amount=amount
    deal.deadline=deadline
    deal.payment_due_date=(d.get('payment_due_date') or '').strip()
    deal.brief=(d.get('brief') or '').strip()
    if deadline: sync_collaboration_deadline(deal)
    create_notification(deal.creator_id,'Campaign details updated',f'{deal.title} details or deadline were updated by the company.','partnership',url_for('deal_room',collab_id=deal.id))
    db.session.commit()
    flash('Agreement saved. The creator task and calendar deadline have been synced.','success')
    return redirect(url_for('deal_room',collab_id=deal.id))

@app.post('/deals/<int:collab_id>/deliverables')
@account_required('company')
def deal_deliverable_add(collab_id):
    deal=Collaboration.query.filter_by(id=collab_id,company_id=current_user.id).first_or_404()
    title=(request.form.get('title') or '').strip()
    if not title: flash('Enter a deliverable title.','error')
    else:
        db.session.add(CollaborationDeliverable(collaboration_id=deal.id,title=title[:220],due_date=(request.form.get('due_date') or '').strip(),notes=(request.form.get('notes') or '').strip()))
        create_notification(deal.creator_id,'New deliverable added',f'{title} was added to {deal.title}.','partnership',url_for('deal_room',collab_id=deal.id))
        db.session.commit(); flash('Deliverable added.','success')
    return redirect(url_for('deal_room',collab_id=deal.id))

@app.post('/deals/<int:collab_id>/deliverables/<int:item_id>/submit')
@account_required('individual')
def deal_deliverable_submit(collab_id,item_id):
    deal=Collaboration.query.filter_by(id=collab_id,creator_id=current_user.id).first_or_404()
    item=CollaborationDeliverable.query.filter_by(id=item_id,collaboration_id=deal.id).first_or_404()
    url=(request.form.get('submission_url') or '').strip()
    if url and not re.match(r'^https?://',url,re.I): flash('Enter a valid link beginning with http:// or https://.','error')
    else:
        item.submission_url=url; item.status='Submitted' if url else 'Not submitted'
        create_notification(deal.company_id,'Creator submitted work',f'{current_user.name} updated the submission for {item.title}.','partnership',url_for('deal_room',collab_id=deal.id))
        db.session.commit(); flash('Submission updated.','success')
    return redirect(url_for('deal_room',collab_id=deal.id))

@app.post('/deals/<int:collab_id>/deliverables/<int:item_id>/review')
@account_required('company')
def deal_deliverable_review(collab_id,item_id):
    deal=Collaboration.query.filter_by(id=collab_id,company_id=current_user.id).first_or_404()
    item=CollaborationDeliverable.query.filter_by(id=item_id,collaboration_id=deal.id).first_or_404()
    status=request.form.get('status','Submitted')
    if status not in ('Submitted','Approved','Revision requested'): return 'Invalid status',400
    item.status=status; item.notes=(request.form.get('notes') or item.notes or '').strip()
    create_notification(deal.creator_id,'Deliverable reviewed',f'{item.title}: {status}.','partnership',url_for('deal_room',collab_id=deal.id))
    db.session.commit(); flash('Deliverable review saved.','success')
    return redirect(url_for('deal_room',collab_id=deal.id))

@app.get('/creators/<int:creator_id>')
@account_required('company')
def creator_public_profile(creator_id):
    creator=User.query.filter_by(id=creator_id,account_type='individual').first_or_404()
    allowed=Collaboration.query.filter_by(company_id=current_user.id,creator_id=creator.id).first()
    if not allowed: return 'You can view full creator profiles after a collaboration is accepted.',403
    accounts=SocialAccount.query.filter_by(user_id=creator.id).order_by(SocialAccount.platform.asc()).all()
    return render_template('creator_public_profile.html',creator=creator,accounts=accounts)

@app.get('/trust')
@login_required
def trust_center():
    if current_user.account_type=='company':
        collaborations=Collaboration.query.filter_by(company_id=current_user.id).order_by(Collaboration.created_at.desc()).all()
    else:
        collaborations=Collaboration.query.filter_by(creator_id=current_user.id).order_by(Collaboration.created_at.desc()).all()
    public_reviews=CollaborationReview.query.join(Collaboration).filter(
        (Collaboration.company_id==current_user.id) | (Collaboration.creator_id==current_user.id)
    ).all()
    # Only show reviews when both sides have submitted.
    visible=[]
    for review in public_reviews:
        pair=CollaborationReview.query.filter_by(collaboration_id=review.collaboration_id).count()
        if pair==2: visible.append(review)
    return render_template('trust.html',collaborations=collaborations,visible_reviews=visible)

@app.post('/trust/collaborations/<int:collab_id>/complete')
@login_required
def complete_collaboration(collab_id):
    item=Collaboration.query.filter_by(id=collab_id).filter(
        (Collaboration.company_id==current_user.id) | (Collaboration.creator_id==current_user.id)
    ).first_or_404()
    item.status='Completed'; item.completed_at=datetime.utcnow(); db.session.commit()
    flash('Collaboration marked completed. Both sides can now submit a private review.','success')
    return redirect(url_for('trust_center'))

@app.post('/trust/collaborations/<int:collab_id>/payment')
@account_required('company')
def update_collaboration_payment(collab_id):
    item=Collaboration.query.filter_by(id=collab_id,company_id=current_user.id).first_or_404()
    item.agreed_amount=float(request.form.get('amount') or 0)
    item.payment_due_date=request.form.get('due_date','').strip()
    item.payment_status=request.form.get('payment_status','Not paid')
    item.paid_date=request.form.get('paid_date','').strip()
    if item.payment_status=='Paid' and not item.paid_date: item.paid_date=datetime.utcnow().strftime('%Y-%m-%d')
    db.session.commit(); flash('Payment details updated.','success'); return redirect(url_for('trust_center'))

@app.post('/trust/collaborations/<int:collab_id>/review')
@login_required
def submit_collaboration_review(collab_id):
    item=Collaboration.query.filter_by(id=collab_id).filter(
        (Collaboration.company_id==current_user.id) | (Collaboration.creator_id==current_user.id)
    ).first_or_404()
    if item.status!='Completed': flash('Reviews open after the collaboration is marked completed.','error'); return redirect(url_for('trust_center'))
    if CollaborationReview.query.filter_by(collaboration_id=item.id,reviewer_id=current_user.id).first():
        flash('You have already submitted your review.','error'); return redirect(url_for('trust_center'))
    rating=request.form.get('rating',type=int)
    if rating not in range(1,6): flash('Choose a rating from 1 to 5.','error'); return redirect(url_for('trust_center'))
    is_company=current_user.id==item.company_id
    review=CollaborationReview(collaboration_id=item.id,reviewer_id=current_user.id,
        reviewee_id=item.creator_id if is_company else item.company_id,rating=rating,
        payment_rating=request.form.get('payment_rating',type=int) if not is_company else None,
        communication_rating=request.form.get('communication_rating',type=int),comment=request.form.get('comment','').strip())
    db.session.add(review); db.session.commit()
    count=CollaborationReview.query.filter_by(collaboration_id=item.id).count()
    flash('Review submitted privately. It will become visible only after the other party submits theirs.' if count<2 else 'Both reviews are submitted. The reviews are now visible on the Trust Center.','success')
    return redirect(url_for('trust_center'))

@app.get('/profile')
@login_required
def profile(): return render_template('profile.html')

@app.post('/profile/avatar')
@login_required
def upload_profile_avatar():
    file=request.files.get('avatar')
    if not file or not file.filename:
        flash('Choose an image first.', 'error'); return redirect(url_for('profile'))
    ext=os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in {'.png','.jpg','.jpeg','.webp','.gif'}:
        flash('Use a PNG, JPG, WEBP or GIF image.', 'error'); return redirect(url_for('profile'))
    upload_dir=os.path.join(app.static_folder,'uploads','avatars')
    os.makedirs(upload_dir,exist_ok=True)
    filename=f'user-{current_user.id}-{uuid.uuid4().hex[:12]}{ext}'
    file.save(os.path.join(upload_dir,filename))
    current_user.avatar_url=url_for('static',filename=f'uploads/avatars/{filename}')
    db.session.commit()
    flash('Profile picture updated.', 'success')
    return redirect(url_for('profile'))

@app.post('/profile/avatar/remove')
@login_required
def remove_profile_avatar():
    current_user.avatar_url=None; db.session.commit()
    flash('Profile picture removed.', 'success')
    return redirect(url_for('profile'))

@app.post('/profile')
@login_required
def update_profile():
    d=request.form; current_user.name=d.get('name',current_user.name).strip()
    for field in ('category','niche','primary_platform','social_handles','company_name','website','industry','company_size'): setattr(current_user,field,d.get(field,'').strip())
    db.session.commit(); flash('Your profile has been updated.','success'); return redirect(url_for('profile'))

@app.post('/api/ai/profile-assist')
@login_required
def ai_profile_assist():
    niche=(current_user.niche or 'your field').strip(); platform=(current_user.primary_platform or 'social media').strip()
    if current_user.account_type=='individual': suggestion=f"{(current_user.category or 'Creator').title()} focused on {niche}. I create thoughtful, audience-first content on {platform}, turning useful ideas into engaging stories and meaningful community conversations."
    else: suggestion=f"{current_user.company_name or current_user.name} builds meaningful partnerships in {current_user.industry or niche}. We collaborate with relevant creators on {platform} to deliver authentic campaigns with clear goals and measurable outcomes."
    return jsonify(suggestion=suggestion)


@app.get('/company/calendar')
@account_required('company')
def company_calendar():
    deals=Collaboration.query.filter_by(company_id=current_user.id).all()
    events=[]
    for deal in deals:
        if deal.deadline: events.append({'date':deal.deadline,'title':deal.title,'kind':'Creator deadline','partner':deal.creator.name,'url':url_for('deal_room',collab_id=deal.id)})
        if deal.payment_due_date: events.append({'date':deal.payment_due_date,'title':deal.title,'kind':'Payment due','partner':deal.creator.name,'url':url_for('deal_room',collab_id=deal.id)})
        for item in CollaborationDeliverable.query.filter_by(collaboration_id=deal.id).all():
            if item.due_date: events.append({'date':item.due_date,'title':item.title,'kind':'Deliverable','partner':deal.creator.name,'url':url_for('deal_room',collab_id=deal.id)})
    events.sort(key=lambda x:x['date'])
    return render_template('company_calendar.html',events=events)

@app.route('/planner',methods=['GET','POST'])
@login_required
def planner_page():
    if request.method=='POST':
        d=request.form; title=d.get('title','').strip()
        if title:
            db.session.add(ContentPost(user_id=current_user.id,title=title,platform=d.get('platform','Instagram'),content_type=d.get('content_type','Reel'),scheduled_for=d.get('scheduled_for',''),status=d.get('status','Idea'),caption=d.get('caption',''))); db.session.commit(); flash('Content added to your planner.','success')
        return redirect(url_for('planner_page'))
    posts=ContentPost.query.filter_by(user_id=current_user.id).order_by(ContentPost.scheduled_for.asc(),ContentPost.id.desc()).all()
    return render_template('planner.html',posts=posts)
@app.route('/calendar', methods=['GET', 'POST'])
@account_required('individual')
def calendar_page():
    if request.method == 'POST':
        d = request.form
        title = (d.get('title') or '').strip()
        scheduled_for = (d.get('scheduled_for') or '').strip()
        if not title or not scheduled_for:
            flash('Add a title and publishing date to schedule content.', 'error')
            return redirect(url_for('calendar_page', month=(scheduled_for[:7] if len(scheduled_for) >= 7 else None)))
        try:
            datetime.strptime(scheduled_for, '%Y-%m-%dT%H:%M')
        except ValueError:
            try:
                datetime.strptime(scheduled_for, '%Y-%m-%d')
            except ValueError:
                flash('Please choose a valid publishing date and time.', 'error')
                return redirect(url_for('calendar_page'))
        create_notification(current_user.id, 'Content scheduled', f'{title} was added to your content calendar.', 'calendar', url_for('calendar_page'))
        db.session.add(ContentPost(
            user_id=current_user.id, title=title,
            platform=d.get('platform', 'Instagram'),
            content_type=d.get('content_type', 'Post'),
            scheduled_for=scheduled_for,
            status=d.get('status', 'Idea'),
            caption=d.get('caption', '').strip()
        ))
        db.session.commit()
        flash('Content added to your calendar.', 'success')
        return redirect(url_for('calendar_page', month=scheduled_for[:7]))

    month_value = request.args.get('month', '')
    try:
        selected_month = datetime.strptime(month_value, '%Y-%m').date().replace(day=1) if month_value else datetime.utcnow().date().replace(day=1)
    except ValueError:
        selected_month = datetime.utcnow().date().replace(day=1)
    first_weekday, days_in_month = pycalendar.monthrange(selected_month.year, selected_month.month)
    weeks = []
    day = 1
    while day <= days_in_month:
        week = []
        for weekday in range(7):
            if (not weeks and weekday < first_weekday) or day > days_in_month:
                week.append(None)
            else:
                week.append(day)
                day += 1
        weeks.append(week)
    # Keep this view scoped to the signed-in account; dates are stored as local form values.
    month_prefix = selected_month.strftime('%Y-%m')
    posts = ContentPost.query.filter_by(user_id=current_user.id).filter(
        ContentPost.scheduled_for.startswith(month_prefix)
    ).order_by(ContentPost.scheduled_for.asc()).all()
    events_by_day = {}
    for post in posts:
        try:
            event_day = int(post.scheduled_for[:10].split('-')[2])
        except (ValueError, IndexError):
            continue
        events_by_day.setdefault(event_day, []).append(post)
    previous_month = (selected_month.replace(day=1) - __import__('datetime').timedelta(days=1)).strftime('%Y-%m')
    next_month = (selected_month.replace(day=28) + __import__('datetime').timedelta(days=4)).replace(day=1).strftime('%Y-%m')
    month_label = selected_month.strftime('%B %Y')
    return render_template('calendar.html', selected_month=selected_month, month_label=month_label,
                           weeks=weeks, events_by_day=events_by_day, posts=posts,
                           previous_month=previous_month, next_month=next_month,
                           today=datetime.utcnow().date().isoformat())

@app.post('/calendar/<int:post_id>/status')
@account_required('individual')
def calendar_status(post_id):
    item = ContentPost.query.filter_by(id=post_id, user_id=current_user.id).first_or_404()
    allowed = {'Idea', 'Draft', 'Ready', 'Published'}
    new_status = request.form.get('status', item.status)
    if new_status in allowed:
        item.status = new_status
        db.session.commit()
        flash('Calendar item updated.', 'success')
    return redirect(url_for('calendar_page', month=(item.scheduled_for or '')[:7] or None))

@app.post('/calendar/<int:post_id>/delete')
@account_required('individual')
def calendar_delete(post_id):
    item = ContentPost.query.filter_by(id=post_id, user_id=current_user.id).first_or_404()
    month = (item.scheduled_for or '')[:7]
    db.session.delete(item)
    db.session.commit()
    flash('Calendar item removed.', 'success')
    return redirect(url_for('calendar_page', month=month or None))

@app.post('/planner/<int:post_id>/status')
@account_required('individual')
def planner_status(post_id):
    item=ContentPost.query.filter_by(id=post_id,user_id=current_user.id).first_or_404(); item.status=request.form.get('status',item.status); db.session.commit(); flash('Content status updated.','success'); return redirect(url_for('planner_page'))
@app.post('/planner/<int:post_id>/delete')
@account_required('individual')
def planner_delete(post_id):
    item=ContentPost.query.filter_by(id=post_id,user_id=current_user.id).first_or_404(); db.session.delete(item); db.session.commit(); return redirect(url_for('planner_page'))
@app.route('/finance',methods=['GET','POST'])
@login_required
def finance_page():
    if request.method=='POST':
        d=request.form
        try: amount=float(d.get('amount','0'))
        except ValueError: amount=0
        if amount>0: db.session.add(FinanceEntry(user_id=current_user.id,entry_type=d.get('entry_type','Income'),category=d.get('category','Other'),amount=amount,description=d.get('description',''),entry_date=d.get('entry_date',''))); db.session.commit(); flash('Finance entry saved.','success')
        return redirect(url_for('finance_page'))
    entries=FinanceEntry.query.filter_by(user_id=current_user.id).order_by(FinanceEntry.id.desc()).all()
    income=sum(x.amount for x in entries if x.entry_type=='Income'); expenses=sum(x.amount for x in entries if x.entry_type=='Expense')
    return render_template('finance.html',entries=entries,income=income,expenses=expenses,net=income-expenses)
@app.get('/analytics')
@login_required
def analytics_page():
    posts=ContentPost.query.filter_by(user_id=current_user.id).all(); campaigns=Campaign.query.filter_by(user_id=current_user.id).all()
    entries=FinanceEntry.query.filter_by(user_id=current_user.id).all(); income=sum(x.amount for x in entries if x.entry_type=='Income')
    return render_template('analytics.html',posts=posts,campaigns=campaigns,income=income,has_data=bool(posts or campaigns or entries))
@app.get('/notifications')
@login_required
def notifications_page():
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    return render_template('notifications.html', notifications=items)

@app.post('/notifications/<int:notification_id>/read')
@login_required
def notification_read(notification_id):
    item = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    item.is_read = True
    db.session.commit()
    return redirect(item.target_url or url_for('notifications_page'))

@app.post('/notifications/read-all')
@login_required
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    flash('All notifications marked as read.', 'success')
    return redirect(url_for('notifications_page'))

@app.route('/social-accounts', methods=['GET', 'POST'])
@login_required
def social_accounts_page():
    if request.method == 'POST':
        d = request.form
        platform = (d.get('platform') or '').strip()
        handle = (d.get('handle') or '').strip().lstrip('@')
        if platform not in {'Instagram', 'YouTube', 'TikTok', 'Facebook', 'LinkedIn', 'X', 'Twitch', 'Other'} or not handle:
            flash('Choose a platform and enter a username or channel handle.', 'error')
            return redirect(url_for('social_accounts_page'))
        try:
            followers = max(0, int(d.get('followers') or 0))
            engagement = min(100.0, max(0.0, float(d.get('engagement_rate') or 0)))
        except ValueError:
            flash('Followers and engagement rate must be valid numbers.', 'error')
            return redirect(url_for('social_accounts_page'))
        account = SocialAccount(user_id=current_user.id, platform=platform, handle=handle[:120],
                                profile_url=(d.get('profile_url') or '').strip()[:300],
                                followers=followers, engagement_rate=engagement,
                                notes=(d.get('notes') or '').strip()[:300])
        db.session.add(account)
        try:
            db.session.commit()
            create_notification(current_user.id, 'Social profile added', f'{platform} profile @{handle} was added to your workspace.', 'social', url_for('social_accounts_page'))
            db.session.commit()
            flash('Social profile added. Metrics are marked as manually maintained until an official platform connection is configured.', 'success')
        except Exception:
            db.session.rollback()
            flash('That social profile may already be in your account. Check the list and try again.', 'error')
        return redirect(url_for('social_accounts_page'))
    accounts = SocialAccount.query.filter_by(user_id=current_user.id).order_by(SocialAccount.platform.asc()).all()
    return render_template('social_accounts.html', accounts=accounts,
                           total_followers=sum(a.followers for a in accounts))

@app.post('/social-accounts/<int:account_id>/update')
@login_required
def social_account_update(account_id):
    account = SocialAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    try:
        account.followers = max(0, int(request.form.get('followers') or 0))
        account.engagement_rate = min(100.0, max(0.0, float(request.form.get('engagement_rate') or 0)))
        account.profile_url = (request.form.get('profile_url') or '').strip()[:300]
        db.session.commit()
        flash('Social profile metrics updated.', 'success')
    except ValueError:
        db.session.rollback()
        flash('Enter valid numeric metrics.', 'error')
    return redirect(url_for('social_accounts_page'))

@app.post('/social-accounts/<int:account_id>/delete')
@login_required
def social_account_delete(account_id):
    account = SocialAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    db.session.delete(account)
    db.session.commit()
    flash('Social profile removed.', 'success')
    return redirect(url_for('social_accounts_page'))

@app.get('/integrations')
@login_required
def integrations_page(): return render_template('integrations.html')
@app.post('/marketplace/invite/<int:creator_id>')
@account_required('company')
def invite_creator(creator_id):
    creator=User.query.filter_by(id=creator_id,account_type='individual').first_or_404()
    existing=Invitation.query.filter_by(company_id=current_user.id,creator_id=creator.id,status='Pending').first()
    if not existing: db.session.add(Invitation(company_id=current_user.id,creator_id=creator.id,message=request.form.get('message','').strip())); db.session.commit(); flash('Creator invitation sent.','success')
    else: flash('You already have a pending invitation to this creator.','error')
    return redirect(url_for('marketplace'))
@app.post('/invitations/<int:invitation_id>/<action>')
@account_required('individual')
def invitation_action(invitation_id,action):
    inv=Invitation.query.filter_by(id=invitation_id,creator_id=current_user.id).first_or_404()
    if action not in ('accept','decline'): return 'Invalid action',400
    inv.status='Accepted' if action=='accept' else 'Declined'
    if action=='accept': create_collaboration(inv.company_id,inv.creator_id,'Direct creator invitation')
    db.session.commit(); flash('Invitation '+inv.status.lower()+'.','success'); return redirect(url_for('marketplace'))
@app.post('/api/ai/content-kit')
@account_required('individual')
def ai_content_kit():
    d=request.get_json(silent=True) or {}; topic=(d.get('topic') or current_user.niche or 'your niche').strip(); platform=(d.get('platform') or current_user.primary_platform or 'Instagram').strip()
    hooks=[f"I wish I knew this before I started with {topic}.",f"3 things nobody tells you about {topic}.",f"Stop scrolling if you are interested in {topic}."]
    caption=f"Let's talk about {topic}. Here are a few practical things worth trying this week. Save this for later and tell me which tip you want me to break down next.\n\nWhat has your experience been?"
    return jsonify(topic=topic,platform=platform,hooks=hooks,caption=caption,checklist=['Choose one clear takeaway','Write a strong first 2-second hook','Capture B-roll or supporting visuals','Add captions and accessible text','Review the final edit before publishing'])

@app.get('/api/health')
def health(): return jsonify(status='ok',app='COLLAB')


# Gmail OAuth integration. Tokens are stored locally for this prototype;
# production deployments should encrypt and store tokens per user in the database.
@app.get('/gmail/connect')
@login_required
def gmail_connect():
    try:
        from google_auth_oauthlib.flow import Flow

        client_config = {
            'web': {
                'client_id': os.getenv('GOOGLE_CLIENT_ID'),
                'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [url_for('gmail_callback', _external=True)],
            }
        }
        flow = Flow.from_client_config(client_config, scopes=GMAIL_SCOPES)
        flow.redirect_uri = url_for('gmail_callback', _external=True)
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
        )
        session['gmail_oauth_state'] = state
        return redirect(auth_url)
    except Exception as exc:
        print('GMAIL CONNECT ERROR:', repr(exc), flush=True)
        app.logger.exception('Gmail connect failed')
        flash(f'Gmail setup error: {type(exc).__name__}', 'error')
        return redirect(url_for('inbox_page'))


@app.get('/gmail/callback')
@login_required
def gmail_callback():
    print('GMAIL CALLBACK REACHED!', flush=True)
    try:
        from google_auth_oauthlib.flow import Flow

        expected_state = session.get('gmail_oauth_state')
        if not expected_state or request.args.get('state') != expected_state:
            return 'Invalid OAuth state', 400

        if request.args.get('error'):
            raise RuntimeError(f"Google authorization error: {request.args.get('error')}")

        client_config = {
            'web': {
                'client_id': os.getenv('GOOGLE_CLIENT_ID'),
                'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [url_for('gmail_callback', _external=True)],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=GMAIL_SCOPES,
            state=expected_state,
        )
        flow.redirect_uri = url_for('gmail_callback', _external=True)
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials

        token_data = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': creds.scopes,
        }
        token_path = f'gmail-token-{current_user.id}.json'
        with open(token_path, 'w', encoding='utf-8') as token_file:
            json.dump(token_data, token_file)

        session.pop('gmail_oauth_state', None)
        flash('Gmail connected. You can now sync messages.', 'success')
    except Exception as exc:
        print('GMAIL OAUTH CALLBACK ERROR:', repr(exc), flush=True)
        app.logger.exception('Gmail OAuth callback failed')
        flash(f'Gmail connection failed: {type(exc).__name__}', 'error')

    return redirect(url_for('inbox_page'))

with app.app_context():
    db.create_all()
    # Upgrade databases created by the first prototype without deleting user data.
    from sqlalchemy import inspect
    inspector=inspect(db.engine)
    user_cols={c['name'] for c in inspector.get_columns('user')}
    if 'avatar_url' not in user_cols: db.session.execute(db.text('ALTER TABLE user ADD COLUMN avatar_url VARCHAR(500)'))
    for table in ('task','idea','campaign','email'):
        cols={c['name'] for c in inspector.get_columns(table)}
        if 'user_id' not in cols: db.session.execute(db.text(f'ALTER TABLE {table} ADD COLUMN user_id INTEGER'))
    # Safe additive upgrades for existing SQLite databases; existing user data is preserved.
    inspector=inspect(db.engine)
    for table, column, sql_type in [('collaboration','deadline','VARCHAR(20)'),('collaboration','brief','TEXT'),('task','collaboration_id','INTEGER'),('content_post','collaboration_id','INTEGER')]:
        cols={c['name'] for c in inspector.get_columns(table)}
        if column not in cols: db.session.execute(db.text(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}'))
    db.session.commit()

if __name__=='__main__': app.run(debug=os.getenv('FLASK_DEBUG','false').lower()=='true',host='127.0.0.1',port=int(os.getenv('PORT','5000')))
