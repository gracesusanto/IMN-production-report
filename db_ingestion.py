import csv
import os.path

from sqlalchemy.orm import sessionmaker

import database
import models


session = sessionmaker(autocommit=False, autoflush=False,
                                      bind=database.get_engine())()

def tooling_not_null(i, offset):
    return i[7 + offset] != ''

def get_tooling_id(i, offset):
    return f'TL-{i[7 + offset]}-{i[6 + offset]}'.replace(" ", "-").replace("/", "-OF-")

def extract_tooling(i, offset):
    tooling_id = get_tooling_id(i, offset)
    if tooling_not_null(i, offset):
        return models.Tooling(**{
            'id' : tooling_id,
            'customer' : i[2 + offset],
            'part_no' : i[3 + offset],
            'part_name' : i[4 + offset],
            'child_part_name' : i[5 + offset], 
            'kode_tooling' : i[6 + offset],
            'common_tooling_name' : i[7 + offset], 
            'proses' : i[8 + offset],
            'std_jam' : int(''.join(filter(str.isalnum, i[9 + offset])))
        })
    return None
    

def mesin_not_null(i, offset):
    return i[0 + offset] != ''

def get_mesin_id(i, offset):
    return f'MC-{i[0 + offset]}'.replace(" ", "-")

def extract_mesin(i, offset):
    mesin_id = get_mesin_id(i, offset)
    if mesin_not_null(i, offset):
        return models.Mesin(**{
            'id' : mesin_id,
            'name' : i[0 + offset],
            'tonase' : int(''.join(filter(str.isalnum, i[1])))
        })
    return None

def operator_not_null(i, offset):
    return i[0 + offset] != ''

def get_operator_id(i, offset):
    return f'OP-{i[0 + offset].title()}'.replace(" ", "-")

def extract_operator(i, offset):
    operator_id = get_operator_id(i, offset)
    if operator_not_null(i, offset):
        return models.Operator(**{
            'id' : operator_id,
            'name' : i[0 + offset].title()
        })
    return None

def import_data(filename, model, get_id, extract_data, data_not_null, offset):
    if not os.path.isfile(filename):
        print(f"{filename} file not found")
        return
        
    with open(filename, newline='') as csvfile:
        try:
            dialect = csv.Sniffer().sniff(csvfile.readline(), delimiters=";,")
            csvfile.seek(0)
            csvreader = list(csv.reader(csvfile, dialect))
        except:
            csvreader = list(csv.reader(csvfile, delimiter=","))
        all_data_id = [ data.id for data in session.query(model).distinct() ]
        data_to_input = { get_id(i, offset) : extract_data(i, offset) for i in csvreader[1:] \
            if (data_not_null(i, offset) and get_id(i, offset) not in all_data_id) }
        session.add_all(list(data_to_input.values()))

def import_tooling(filename, offset=0):
    import_data(
        filename=filename,
        model=models.Tooling,
        get_id=get_tooling_id,
        extract_data=extract_tooling,
        data_not_null=tooling_not_null,
        offset=offset,
    )

def import_mesin(filename, offset=0):
    import_data(
        filename=filename,
        model=models.Mesin,
        get_id=get_mesin_id,
        extract_data=extract_mesin,
        data_not_null=mesin_not_null,
        offset=offset,
    )

def import_operator(filename, offset=0):
    import_data(
        filename=filename,
        model=models.Operator,
        get_id=get_operator_id,
        extract_data=extract_operator,
        data_not_null=operator_not_null,
        offset=offset,
    )

def import_to_db(filename):
    header = ['M/C','Tonase','Customer','Part No.','Part Name','Child Part Name','Kode Tooling','Common Tooling Name','Proses','STD Jam (Pcs)','Operator']
    if os.path.isfile(filename):
        with open(filename, newline='') as csvfile:
            try:
                dialect = csv.Sniffer().sniff(csvfile.readline(), delimiters=";,")
                csvfile.seek(0)
                csvreader = list(csv.reader(csvfile, dialect))
            except:
                csvreader = list(csv.reader(csvfile, delimiter=","))

            if list(map(str.strip, csvreader[0])) != header:
                print("Failed to read header")
                return

    # Import Tooling Data
    import_tooling(filename)

    # Import Mesin
    import_mesin(filename)

    # Import Operator Data
    import_operator(filename, offset=10)

    session.commit()

    import_mesin('db_mesin.csv')
    import_operator('db_operator.csv')
    session.commit()


if __name__ == '__main__':
    import_to_db('data_all.csv')
    print("db ingestion complete")