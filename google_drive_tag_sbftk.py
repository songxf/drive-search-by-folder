'''
Created on Apr 4, 2015

@author: xsong
'''

import json
import httplib2
import pprint

from apiclient.discovery import build
from apiclient.http import MediaFileUpload
from apiclient.errors import HttpError
from oauth2client.client import OAuth2WebServerFlow, Credentials
import os
import time
import logging

__cache = {"retry": 3}

def get_logger():
    logger = logging.Logger('google_drive_tag_sbftk')
    streamHandler = logging.StreamHandler()
    formatter=logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    streamHandler.setFormatter(formatter)
    logger.addHandler(streamHandler)
    return logger
    
def get_credentials():
    if __cache.has_key('credentials'):
        return __cache['credentials']
    elif os.path.exists('%s/.googledrive'%os.environ['HOME'] ):
        ss = open('%s/.googledrive'%os.environ['HOME']).read()
        credentials = Credentials.new_from_json( ss )
    else:
        # Copy your credentials from the APIs Console
        CLIENT_ID = 'your client id'
        CLIENT_SECRET = 'your client secrete'
        REDIRECT_URI = 'your redirect uri'
        # Check https://developers.google.com/drive/scopes for all available scopes
        OAUTH_SCOPE = 'https://www.googleapis.com/auth/drive'
    
        # Run through the OAuth flow and retrieve credentials
        flow = OAuth2WebServerFlow(CLIENT_ID, CLIENT_SECRET, OAUTH_SCOPE, REDIRECT_URI)
        authorize_url = flow.step1_get_authorize_url()
        print 'Go to the following link in your browser: ' + authorize_url
        code = raw_input('Enter verification code: ').strip()
        credentials = flow.step2_exchange(code)
        f = open('%s/.googledrive'%os.environ['HOME'], 'w')
        f.write(credentials.to_json())
        f.close()
        
    return credentials

def _retry_(f):
    def _f(*args, **kwargs):
        success = False
        res = []
        retry = __cache['retry']
        while not success and retry > 0:
            try:
                res = f(*args, **kwargs)
                success = True
            except Exception, err:
                retry -=1
                if retry > 0:
                    log.info('Some errors in %s: %s. Retry after 5 seconds'%(f, err))
                    time.sleep(5)
        return res
    
    return _f

def get_access_token():
    credentials = get_credentials()    
    # Create an httplib2.Http object and authorize it with our credentials
    http = httplib2.Http()
    credentials.refresh(http)
    return credentials

@_retry_
def get_drive_service():
    if __cache.has_key('drive_service'):
        return __cache['drive_service']
    
    credentials = get_credentials()    
    # Create an httplib2.Http object and authorize it with our credentials
    http = httplib2.Http()
    if credentials.access_token_expired:
        credentials.refresh(http)
        f = open('%s/.googledrive'%os.environ['HOME'],'w' )
        f.write(credentials.to_json())
        f.flush()
        f.close()

    http = credentials.authorize(http)
    drive_service = build('drive', 'v2', http=http)
    __cache['drive_service'] = drive_service
    return drive_service

@_retry_
def patch_file(fileId, body, setModifiedDate = True, updateViewedDate = False, fields = None):
    return get_drive_service().files().patch( fileId = fileId, body = body, 
                                              setModifiedDate = setModifiedDate, 
                                              updateViewedDate = updateViewedDate, 
                                              fields = fields).execute()

@_retry_
def get_files(q, page_token = None, maxResults = 100, fields = None):
    """Example of q: "mimeType = 'image/jpeg' and trashed = false and not fullText contains 'Photo:ByTime'"
       Example of fields: "id,labels/starred"
    """
    files = get_drive_service().files()
    if page_token == None:
        res = files.list(q = q, maxResults = maxResults, fields = fields).execute()
    else:
        res = files.list(q = q, maxResults = maxResults, pageToken = page_token, fields = fields).execute()
    return res

@_retry_
def get_file(fileId, fields = None):
    files = get_drive_service().files() 
    res = files.get(fileId = fileId, fields = fields).execute()
    return res


def get_all_items():
    """Get All itmes"""
    files = get_drive_service().files() 
    fields = 'items(id,description,parents/id,title,mimeType),nextPageToken'
    items = []
    maxNum = 1000
    res = files.list(q = 'trashed = false', pageToken = None, maxResults = maxNum, fields = fields).execute()
    items.extend(res['items'])
    count = 1
    while res.has_key('nextPageToken'):
        log.info('nextPageToken %d: %s'% (count, res['nextPageToken'] ))
        res = files.list(q = 'trashed = false', pageToken = res['nextPageToken'], maxResults = maxNum, fields = fields).execute()
        items.extend(res['items'])
        count += 1
    return items

if __name__ == "__main__":
    log = get_logger()
    items = get_all_items()
    """Arrange folders"""    
    folders = [x for x in items if x['mimeType'] == 'application/vnd.google-apps.folder']
    folder_names = {}
    folder_map = {}
    inverse_map = {}
    for f in folders:
        folder_names[ f['id']] = f['title']
        pids = [ x['id'] for x in f['parents']]
        pids.sort()
        inverse_map[ f['id'] ] = pids 
        for f1 in f['parents']:
            folder_map.setdefault(f1['id'], [])
            folder_map[ f1['id'] ].append( f['id'] )
           
    #by exploring the parents of your top level document, you can easily find this. 
    root = 'find_your_root_id'
    if not folder_names.has_key(root):
        folder_names[root] = '/'

    def get_abs_path(pid):
        try:
            if pid == root:
                return ''
            else:
                return get_abs_path(inverse_map[pid][0]) + '/' + folder_names[pid] 
        except:
            log.error('Error getting abs_path for %s'%pid)
            return ''
    
    def get_base_path(pid):
        try:
            return folder_names[pid]
        except:
            log.error('Error getting base_path for %s'%pid)
            return ''
        
    files = [x for x in items if x['mimeType'] != 'application/vnd.google-apps.folder']
    
    def get_new_desc(fres):
        desc = fres.get('description', '')
        slines = desc.split('\n')
        slines = [ x for x in slines if not x.startswith('SBFTK') ]
        pids = [x['id'] for x in fres['parents']]
        pids.sort()
        for pid in pids:
            abs_path = get_abs_path(pid)
            if abs_path != "":
                slines.append('SBFTK:folder:%s'%get_abs_path(pid))
                slines.append('SBFTK:folder:%s'%get_base_path(pid))
            else:
                log.info('abs path is empty for %s: https://docs.google.com/file/d/%s/edit'%(fres['id'], fres['id']))
        desc1 = '\n'.join(slines)
        return desc1
    
    files = [x for x in items if x['mimeType'] != 'application/vnd.google-apps.folder']
    count = 0
    for f in files:
        fid = f['id']
        desc0 = get_new_desc(f)
        if desc0 == f.get('description', ''):
            count +=1 
            continue
        
        log.info('getting %d/%d: %s'%(count, len(files), fid))
        fres = get_file(fid, fields = 'id,parents/id,modifiedDate,description'  )
        desc1 = get_new_desc(fres)
        if desc1 != fres.get('description', ''):
            log.info('old desc: %s'%fres.get('description', ''))
            log.info('new desc: %s'%desc1)
            body = {'description': desc1, 'modifiedDate': fres['modifiedDate'] }
            fres2 = patch_file(fid, body, fields = 'id,parents/id,modifiedDate,description,title')
            if len(fres2) != 0:
                log.info( 'Modified: %s'% json.dumps( fres2, indent=4))
                log.info( '    Link: https://docs.google.com/file/d/%s/view'%fres2['id'] )
                log.info( '    Parent: https://drive.google.com/open?id=%s&authuser=0'% fres2['parents'][0]['id'] )
            else:
                log.info( 'Can not modify the description: %s'%fres['id']) 
                log.info('    Link: https://docs.google.com/file/d/%s/view'%fres['id'] )
                log.info('    Parent: https://drive.google.com/open?id=%s&authuser=0'%fres['parents'][0]['id'])
        count +=1