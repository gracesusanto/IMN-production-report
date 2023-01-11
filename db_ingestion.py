import csv
from time import time

from sqlalchemy.orm import sessionmaker

import database
import models


session = sessionmaker(autocommit=False, autoflush=False,
                                      bind=database.get_engine())()

def import_to_db(filename):
    with open(filename, newline='') as csvfile:
        spamreader = csv.reader(csvfile, delimiter=',')
        for i in spamreader:
            if (i[6] != ''):
                tooling = models.Tooling(**{
                    'id' : f'TL-{i[6]}',
                    'customer' : i[2],
                    'part_no' : i[3],
                    'part_name' : i[4],
                    'child_part_name' : i[5], 
                    'kode_tooling' : i[6],
                    'common_tooling_name' : i[7], 
                    'proses' : i[8],
                    'std_jam' : int(i[9])
                })
                session.add(tooling) #Add all the records

            if (i[0] != ''):
                mesin = models.Mesin(**{
                    'id' : f'MC-{i[0]}',
                    'name' : i[0],
                    'tonase' : int(i[1])
                })
                session.add(mesin)

            if (i[10] != ''):
                operator = models.Operator(**{
                    'id' : f'OP-{i[10].title()}',
                    'name' : i[10].title()
                })
                session.add(operator)
        session.commit()

if __name__ == '__main__':
    import_to_db('db.csv')