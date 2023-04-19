import os
# Import Boto and deps for S3
import boto3
from dotenv import load_dotenv

load_dotenv()


s3_bucket = os.environ['S3_BUCKET']
topic_arn = os.environ['TOPIC_ARN']


# S3 Boto definitions
s3 = boto3.client('s3')

# SNS Boto definitions
sns_client = boto3.client('sns')


def s3_put_website_redirect(key, website_redirect_location):
    """
    Create a website redirection on an S3 bucket

    :param key: the filename (or key as AWS calls it)
    :param website_redirect_location: the url we should redirect to
    :return:
    """
    s3.put_object(Bucket=s3_bucket, Key=key, Body='0', WebsiteRedirectLocation=f"/{website_redirect_location}")


def send_to_sns_topic(message):
    """
    Send a message to an SNS topic

    :param message: content of the message to send
    :return:
    """
    print(sns_client.publish(TopicArn=topic_arn, Message=message))
