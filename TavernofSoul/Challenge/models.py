from django.db import models
from django.urls import reverse

# Create your models here.

class ChallengeModeAutoMap(models.Model):
    """
    챌린지 모드 자동 맵 정보를 저장하는 모델
    IES 파일: challenge_mode_auto_map.ies
    """
    class_id = models.IntegerField(db_index=True, unique=True, help_text="ClassID")
    class_name = models.CharField(max_length=50, db_index=True, help_text="ClassName")
    map_name = models.CharField(max_length=100, db_index=True, help_text="MapName")
    name = models.CharField(max_length=200, help_text="Name (한글 맵 이름)")
    value_str = models.CharField(max_length=200, blank=True, null=True, help_text="Value_Str")
    
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Challenge Mode Auto Map"
        verbose_name_plural = "Challenge Mode Auto Maps"
        ordering = ['class_id']
    
    def __str__(self):
        return f"{self.class_id}: {self.name} ({self.map_name})"
    
    def get_absolute_url(self):
        return reverse('Challenge:detail', args=[str(self.class_id)])
