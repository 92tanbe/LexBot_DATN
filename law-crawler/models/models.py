from peewee import *

from db import db


class BaseModel(Model):
    class Meta:
        database = db


class PDChuDe(BaseModel):
    id = CharField(max_length=128, primary_key=True)
    ten = TextField()
    stt = IntegerField()


class PDDeMuc(BaseModel):
    id = CharField(max_length=128, primary_key=True)
    ten = TextField()
    stt = IntegerField()
    chude_id = ForeignKeyField(PDChuDe, backref="demucs")


class PDChuong(BaseModel):
    mapc = CharField(max_length=128, primary_key=True)
    ten = TextField()
    demuc_id = ForeignKeyField(PDDeMuc, backref="chuongs")
    chimuc = TextField()
    stt = IntegerField()


class PDDieu(BaseModel):
    id = CharField(max_length=128, primary_key=True)
    title = TextField()
    content = TextField()
    demuc_id = ForeignKeyField(PDDeMuc, backref="dieus", column_name="demuc_id")
    chuong_id = ForeignKeyField(PDChuong, backref="dieus", column_name="chuong_id")


class PDTable(BaseModel):
    dieu_id = ForeignKeyField(PDDieu, backref="tables")
    html = TextField()


class PDFile(BaseModel):
    dieu_id = ForeignKeyField(PDDieu, backref="files")
    link = TextField()
    path = TextField()


class PDMucLienQuan(BaseModel):
    dieu_id1 = ForeignKeyField(PDDieu)
    dieu_id2 = ForeignKeyField(PDDieu)
