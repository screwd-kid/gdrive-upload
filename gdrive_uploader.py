#!/usr/bin/python
from __future__ import absolute_import
from __future__ import print_function

import os
import time
import sys
import logging

from apiclient import errors as api_errors, http as api_http

logger = logging.getLogger(__name__)


def get_file_data(service, filename, folder_id=None):
    """
    Search for filename in specific folder name in target account and return file data if match
    :param service: gdrive api service
    :param filename: name of file we want to search
    :param folder_id: id of target folder name
    :return:
        file in gdrive that match condition or None
    """
    file_data = None
    # search for folder name
    try:
        if folder_id:
            q = 'name="{}" and "{}" in parents'.format(filename, folder_id)
        else:
            q = 'name="{}"'.format(filename)

        logger.debug('Check file on gdrive: q=[%s]', q)
        items = files.get('files', [])
        if items:
            logger.debug('Found on gdrive: %s', items)
            file_data = items[0]
    except api_errors.HttpError as error:
        logger.error('HTTP error in get_file_data: %s', error)
    except:
        logger.error('An error occurred in get_file_data: [%s] %s ', sys.exc_info()[0], sys.exc_info()[1])

    logger.debug('Get file data for [%s] in [%s] : %s', filename, folder_id, file_data)
    return file_data


def get_or_create_folder(service, folder_name):
    """
    Search for specific folder name in target account and create one if not exist
    then return folder id
    :param service: gdrive api service
    :param folder_name: string of target folder name
    :return:
        folder id in gdrive
    """
    folder_id = None
    # search for folder name
    q = 'name="{}" and trashed!=true and mimeType="application/vnd.google-apps.folder"'.format(folder_name)
    try:
        files = service.files().list(q=q).execute()
        items = files.get('files', [])
        if items:
            folder_id = items[0]['id']
            logger.debug('Found folder [%s]: %s', folder_name, folder_id)
        else:
            logger.debug('Not found folder [%s], try to create new folder', folder_name)
            body = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            request = service.files().create(body=body).execute()
            folder_id = request['id']
            logger.debug('Created new folder [%s]: %s', folder_name, folder_id)
    except api_errors.HttpError as error:
        logger.error('HTTP error in get_or_create_folder: %s', error)
    except:
        logger.error('An error occurred in get_or_create_folder: %s ', sys.exc_info()[0])
    return folder_id


def upload_file(service, input_file, output_name=None, folder_name=None, show_progress=False):
    """
    Upload file to gdrive using MediaFileUpload that support large file upload and resumable
    Display upload speed and progress when call this function
    :param service: gdrive api service
    :param input_file: full path or relative path to source file to upload
    :param output_name: target filename on gdrive, if none, use same name as source filename
    :param folder_name: target folder name to store file. this folder will create under root folder on gdrive
    :return:
        File instance from google api or None if error occur
    """

    # filename, ext = os.path.splitext(input_file)
    mime_type = 'application/octet-stream'

    if not output_name:
        output_name = os.path.basename(input_file)
    body = {
        'name': output_name,
    }
    if folder_name:
        parent_id = get_or_create_folder(service, folder_name)
        body['parents'] = [parent_id]

    logger.debug('Prepare file to upload [%s] mime[%s] chunk[%s] body[%s]', input_file, mime_type, 1048576, body)
    media = api_http.MediaFileUpload(input_file, mimetype=mime_type, chunksize=1048576, resumable=True)
    request = service.files().create(media_body=media, body=body)

    logger.info("Upload : %s", input_file)
    start_time = time.time()
    status = None
    response = None
    last_progress = 0
    idle_count = 0

    while response is None:
        if idle_count >= 5:
            logger.debug('Max idle retry for upload')
            break

        try:
            status, response = request.next_chunk()
        except api_errors.HttpError as error:
            if error.resp.status in [404]:
                # Start the upload all over again.
                logger.error('Upload fail 404 retry all over again: %s' % error)
                break
            elif error.resp.status in [500, 502, 503, 504]:
                # Call next_chunk() again, but use an exponential backoff for repeated errors.
                logger.error('Upload fail 50X retry next_chunk: %s' % error)
                idle_count += 1
                time.sleep(idle_count*idle_count)
                continue
            else:
                # Do not retry. Log the error and fail.
                logger.error('Upload fail HTTP error in next_chunk: %s', error)
                break
        except:
            logger.error('Upload fail An error occurred in next_chunk: [%s] %s ', sys.exc_info()[0], sys.exc_info()[1])
            break

        if status:
            if last_progress >= status.resumable_progress:
                idle_count += 1
            else:
                idle_count = 0

            upload_speed = int(status.resumable_progress / (1024*(time.time() - start_time)))
            logger.debug("Uploaded {}% - ({:,}/{:,}) - Avg {:,} Kps".format(
                        int(status.progress() * 100),
                        status.resumable_progress,
                        status.total_size,
                        upload_speed))
            if show_progress:
                print("Uploaded {}% - ({:,}/{:,}) - Avg {:,} Kps".format(
                    int(status.progress() * 100),
                    status.resumable_progress,
                    status.total_size,
                    upload_speed), end='\r')
            last_progress = status.resumable_progress
        else:
            logger.debug('Not receive status from status, response = request.next_chunk()')
            idle_count += 1

    if response:
        logger.info("Upload {} Complete! -- {:,} seconds".format(input_file, time.time() - start_time))
        return True
    else:
        logger.error("Upload {} Error! -- {:,} seconds".format(input_file, time.time() - start_time))
        return False
