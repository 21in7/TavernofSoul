from django.db import models

# Create your models here.


class Version (models.Model):
	version 	 	= models.CharField(max_length=50, unique=True)
	created 		= models.DateTimeField(auto_now_add=True)

