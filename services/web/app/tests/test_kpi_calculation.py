"""
Test KPI calculation and response format for Report Table
"""
import unittest
import pandas as pd
from datetime import datetime
from app.service import report_summary as rs
from app.cmd.generate_report import ReportCategory
import app.service.utils as ru


class TestKpiCalculation(unittest.TestCase):
    """Test KPI calculation logic"""

    def setUp(self):
        """Set up test data"""
        self.mock_raw_data = pd.DataFrame([
            # Normal runtime activity
            {
                'Tanggal': '2024-01-15',
                'Shift': '1',
                'MC': 'M001',
                'Part No': 'P001',
                'Part Name': 'Test Part',
                'Proses': 'MACHINING',
                'Operator': 'OP001',
                'Target': 100,  # 100 parts per hour
                'Qty': 80,      # Actual output
                'Reject': 5,    # Reject count
                'Rework': 2,    # Rework count
                'Keterangan': 'Normal production',
                '_StartTs': ru.JAKAUA_TZ.localize(datetime(2024, 1, 15, 7, 0, 0)),
                '_StopTs': ru.JAKAUA_TZ.localize(datetime(2024, 1, 15, 8, 0, 0)),
                '_DurationMinutes': 60,
                'Desc': 'U : Utility'
            },
            # Tool change downtime
            {
                'Tanggal': '2024-01-15',
                'Shift': '1',
                'MC': 'M001',
                'Part No': 'P001',
                'Part Name': 'Test Part',
                'Proses': 'MACHINING',
                'Operator': 'OP001',
                'Target': 100,
                'Qty': 0,       # No output during tool change
                'Reject': 0,
                'Rework': 0,
                'Keterangan': 'Tool change required',
                '_StartTs': ru.JAKAUA_TZ.localize(datetime(2024, 1, 15, 8, 0, 0)),
                '_StopTs': ru.JAKAUA_TZ.localize(datetime(2024, 1, 15, 8, 30, 0)),
                '_DurationMinutes': 30,
                'Desc': 'TP : Tooling Problem'
            },
            # More runtime
            {
                'Tanggal': '2024-01-15',
                'Shift': '1',
                'MC': 'M001',
                'Part No': 'P001',
                'Part Name': 'Test Part',
                'Proses': 'MACHINING',
                'Operator': 'OP001',
                'Target': 100,
                'Qty': 40,      # More output
                'Reject': 2,
                'Rework': 1,
                'Keterangan': 'Resumed production',
                '_StartTs': ru.JAKAUA_TZ.localize(datetime(2024, 1, 15, 8, 30, 0)),
                '_StopTs': ru.JAKAUA_TZ.localize(datetime(2024, 1, 15, 9, 0, 0)),
                '_DurationMinutes': 30,
                'Desc': 'U : Utility'
            }
        ])

    def test_summarize_dashboard_df(self):
        """Test that summarize_dashboard_df produces correct KPIs"""
        # Test the main summarization function
        summarized = rs.summarize_dashboard_df(self.mock_raw_data, ReportCategory.MESIN)

        self.assertFalse(summarized.empty, "Summarized data should not be empty")
        self.assertEqual(len(summarized), 1, "Should produce one summarized row")

        row = summarized.iloc[0]

        # Test basic aggregation
        self.assertEqual(row['Qty'], 120, "Total output should be 80+40=120")
        self.assertEqual(row['Reject'], 7, "Total reject should be 5+2=7")
        self.assertEqual(row['Target'], 100, "Target should be 100")

        # Test time calculations
        self.assertEqual(row['Plan Minutes'], 120.0, "Plan should be U+TP = 90+30 = 120 minutes")
        self.assertEqual(row['Utility Minutes'], 90.0, "Utility should be U = 60+30 = 90 minutes")

        # Test formatted time fields
        self.assertEqual(row['Plan'], "02:00", "Plan should be formatted as 02:00")
        self.assertEqual(row['Utility'], "01:30", "Utility should be formatted as 01:30")
        self.assertEqual(row['TP'], "00:30", "TP should be formatted as 00:30")

        # Test KPI calculations
        self.assertAlmostEqual(row['OTR Num'], 75.0, places=1, msg="OTR should be 90/120 = 75%")
        self.assertAlmostEqual(row['PER Num'], 86.67, places=1, msg="PER should be ~86.67%")
        self.assertAlmostEqual(row['QR Num'], 92.31, places=1, msg="QR should be 120/130 = ~92.31%")
        self.assertAlmostEqual(row['OEE Num'], 60.0, places=0, msg="OEE should be ~60%")

        # Test formatted KPI fields
        self.assertEqual(row['OTR'], "75%", "OTR should be formatted as 75%")
        self.assertEqual(row['PER'], "87%", "PER should be formatted as 87%")
        self.assertEqual(row['QR'], "92%", "QR should be formatted as 92%")
        self.assertEqual(row['OEE'], "60%", "OEE should be formatted as 60%")

    def test_build_detail_export_response(self):
        """Test that build_detail_export_response formats data correctly"""
        # First summarize the data
        summarized = rs.summarize_dashboard_df(self.mock_raw_data, ReportCategory.MESIN)

        # Then build the response
        response = rs.build_detail_export_response(summarized, ReportCategory.MESIN)

        self.assertIn('rows', response)
        self.assertIn('total', response)
        self.assertEqual(response['total'], 1)
        self.assertEqual(len(response['rows']), 1)

        row = response['rows'][0]

        # Test basic fields
        self.assertEqual(row['mc_no'], 'M001')
        self.assertEqual(row['output'], 120)
        self.assertEqual(row['reject'], 7)
        self.assertEqual(row['target_per_jam'], 100)

        # Test time fields are not 00:00
        self.assertNotEqual(row['plan'], '00:00', "Plan time should not be 00:00")
        self.assertNotEqual(row['rt'], '00:00', "Runtime should not be 00:00")
        self.assertEqual(row['plan'], '02:00', "Plan should be 02:00")
        self.assertEqual(row['rt'], '01:30', "Runtime should be 01:30")
        self.assertEqual(row['tp'], '00:30', "TP should be 00:30")

        # Test KPI fields are not 0%
        self.assertNotEqual(row['per'], '0%', "PER should not be 0%")
        self.assertNotEqual(row['otr'], '0%', "OTR should not be 0%")
        self.assertNotEqual(row['oee'], '0%', "OEE should not be 0%")

        # Test actual KPI values
        self.assertEqual(row['otr'], '75%', "OTR should be 75%")
        self.assertEqual(row['per'], '87%', "PER should be 87%")
        self.assertEqual(row['qr'], '92%', "QR should be 92%")
        self.assertEqual(row['oee'], '60%', "OEE should be 60%")

        # Test catatan is summarized, not raw transition text
        catatan = row['catatan']
        self.assertNotIn(' -> ', catatan, "Catatan should not contain raw transition arrows")
        self.assertIn('Normal production', catatan, "Catatan should contain business context")

    def test_no_raw_transition_data(self):
        """Test that the response doesn't contain raw transition data markers"""
        summarized = rs.summarize_dashboard_df(self.mock_raw_data, ReportCategory.MESIN)
        response = rs.build_detail_export_response(summarized, ReportCategory.MESIN)

        row = response['rows'][0]
        catatan = row['catatan']

        # These are indicators of raw transition data, not business summary
        self.assertNotIn('stop', catatan.lower(), "Should not contain 'stop' from raw transitions")
        self.assertNotIn(' -> ', catatan, "Should not contain transition arrows")
        self.assertNotIn('TL1', catatan, "Should not contain raw machine codes")

    def test_time_buckets_not_zero(self):
        """Test that time buckets are properly calculated and not all zero"""
        summarized = rs.summarize_dashboard_df(self.mock_raw_data, ReportCategory.MESIN)
        response = rs.build_detail_export_response(summarized, ReportCategory.MESIN)

        row = response['rows'][0]

        # At least some time fields should be non-zero
        time_fields = ['plan', 'rt', 'tp']
        non_zero_times = [field for field in time_fields if row[field] != '00:00']

        self.assertGreater(len(non_zero_times), 0,
                          f"At least some time fields should be non-zero: {time_fields}")

        # Specifically check the expected ones
        self.assertEqual(row['plan'], '02:00', "Plan should be calculated correctly")
        self.assertEqual(row['rt'], '01:30', "Runtime should be calculated correctly")
        self.assertEqual(row['tp'], '00:30', "TP should be calculated correctly")


if __name__ == '__main__':
    unittest.main()