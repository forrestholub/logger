# AI prompt:
# search for the input_file_name_match in the current directory and then add all the files that match together into a list. Then, search through that list for rows that contain teh SIP_message_filter and print the results to a new file called "SAMSUNG_SIP_CALL_RESULTS.txt"

import os
import re

import numpy as np
import pandas as pd

# statics:
INPUT_FILE_NAME_MATCH = "logmain.txt"
SIP_MSG_FILTER = "SIPMSG"
OUTPUT_FILE = "SAMSUNG_SIP_CALL_RESULTS"

def create_dataframe_from_sip_messages(sip_messages):
    data = []
    for line in sip_messages:
        parts = re.split(r'\s+', line, maxsplit=8)  # Split by whitespace, limit to 9 parts
        if len(parts) >= 9:
            data.append({
                "Date": parts[0],
                "Time": parts[1],
                "Code": parts[2],
                "Code2": parts[3],
                "Debug_Level": parts[4],
                "Category": parts[5],
                "Message": ' '.join(parts[6:])
            })
    return pd.DataFrame(data)


def find_files_with_pattern(directory, pattern):
    matching_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if re.search(pattern, file):
                matching_files.append(os.path.join(root, file))
    return matching_files


def filter_sip_messages(files, sip_filter):
    # Read matching files, extract lines that match sip_filter, and deduplicate exact duplicate rows
    sip_messages = []
    for file in files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                for line in f:
                    if re.search(sip_filter, line):
                        sip_messages.append(line.strip())
        except UnicodeDecodeError:
            with open(file, 'r', encoding='latin-1') as f:
                for line in f:
                    if re.search(sip_filter, line):
                        sip_messages.append(line.strip())
    # If multiple files contributed, remove exact duplicate rows to reduce overlap
    if len(files) > 1:
        sip_messages = list(dict.fromkeys(sip_messages))  # preserves order while deduping
    return sip_messages


def write_results_to_file(results, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        for line in results:
            f.write(line + '\n')


def main():
    # Find files matching the input pattern
    matching_files = find_files_with_pattern('.', INPUT_FILE_NAME_MATCH)
    # Filter SIP messages from the found files
    sip_messages = filter_sip_messages(matching_files, SIP_MSG_FILTER)
    # Write the filtered SIP messages to the output file
    write_results_to_file(sip_messages, OUTPUT_FILE + ".txt")
    # Print the number of SIP messages found
    print(f"Number of SIP messages found: {len(sip_messages)}")

    # Create a DataFrame from the SIP messages
    sip_df = create_dataframe_from_sip_messages(sip_messages)
    # check the "Direction" column and change the values from "[<--]" to "DL" and from "[-->]" to "UL"
    # sip_df['Direction'] = sip_df['Direction'].replace({'\[<--\]': 'DL', '\[-->\]': 'UL'}, regex=True)

    # add current year to the "Date" column since it's only in format "MM-DD" and we need to add the current year to it
    current_year = pd.Timestamp.now().year
    sip_df['Date'] = sip_df['Date'].apply(lambda x: f"{current_year}/{x}" if len(x.split('-')) == 2 else x)

    # I need to iterate each row in the dataframe when it is filtered by time, ascending, and check the DataFrame where the "Message" column contains the string "user=phone SIP/2.0 [CSeq: 1 INVITE]"
    # which will indicate a new call setup, and then I'll need to create a new column called "CALL_ID" that I'll set equal to 1. And I'll continue to set the next rows "CALL_ID" to 1 until I find a row that contains the string "BYE" in the Message column. Then, i'll incremenet my
    #"CALL_ID" by 1 and continue to set the next rows "CALL_ID" to 2 until I find another row that contains the string "BYE" in the Message column. This will allow me to track each call and its associated messages.
    sip_df['Message'] = sip_df['Message'].astype(str)
    # need to sort the DataFrame by Date and Time to ensure the order is correct
    sip_df.sort_values(by=['Date', 'Time'], ascending=True, inplace=True)
    # after sorting, I need to reset the index of the DataFrame
    sip_df.reset_index(drop=True, inplace=True)

    sip_df['CALL_ID'] = 0
    sip_df['SIP_MSG'] = ''
    sip_df['Direction'] = ''
    sip_df['MSG_ID'] = np.nan
    CALL_ID = 1
    MSG_ID = 0
    BYE_FLAG = False
    NEW_SIP_MSG = False

    for index, row in sip_df.iterrows():
        if "<--" in row['Message']:
            sip_df.at[index, 'Direction'] = "DL"
            NEW_SIP_MSG = True
            MSG_ID += 1
        if "-->" in row['Message']:
            sip_df.at[index, 'Direction'] = "UL"
            NEW_SIP_MSG = True
            MSG_ID += 1
        if 'SIP/2.0 [CSeq: 1 INVITE]' in row['Message']:  # 'user=phone SIP/2.0 [CSeq: 1 INVITE]' only present on MO INVITE
            BYE_FLAG = False
            sip_df.at[index, 'SIP_MSG'] = "INVITE"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif '100 Trying' in row['Message']:
            sip_df.at[index, 'SIP_MSG'] = "100_TRYING"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif '183 Session Progress' in row['Message']:
            sip_df.at[index, 'SIP_MSG'] = "183_SESSION_PROGRESS"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif '180 Ringing' in row['Message']:
            sip_df.at[index, 'SIP_MSG'] = "180_RINGING"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif '200 OK' in row['Message'] and not "BYE" in row['Message']:
            sip_df.at[index, 'SIP_MSG'] = "200_OK"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif 'ACK' in row['Message']:
            sip_df.at[index, 'SIP_MSG'] = "ACK"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif 'CANCEL' in row['Message']:
            sip_df.at[index, 'SIP_MSG'] = "CANCEL"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif 'SIP/2.0 404 Not Found' in row['Message']:
            sip_df.at[index, 'SIP_MSG'] = "404_NOT_FOUND"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
        elif 'BYE' in row['Message'] and not BYE_FLAG:
            sip_df.at[index, 'SIP_MSG'] = "BYE"
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID
            CALL_ID += 1
            BYE_FLAG = True
            NEW_SIP_MSG = False
        elif 'BYE' in row['Message'] and BYE_FLAG:
            # if we already have a BYE_FLAG set, we don't want to increment the CALL_ID again
            sip_df.at[index, 'SIP_MSG'] = "BYE_200_OK"
            sip_df.at[index, 'MSG_ID'] = MSG_ID
            sip_df.at[index, 'CALL_ID'] = CALL_ID - 1
            # but we still want to set the CALL_ID to the current CALL_ID
            # this is to avoid incrementing the CALL_ID for every BYE message
            # since there might be multiple BYE messages in the same call
        else:
            sip_df.at[index, 'CALL_ID'] = CALL_ID
            sip_df.at[index, 'MSG_ID'] = MSG_ID

    # then I want to go through the DataFrame and filter it by the "CALL_ID" column, and look for the time difference between row that contains "user=phone SIP/2.0 [CSeq: 1 INVITE]" and the row that contains "180 Ringing" in the Message column, and then create a new column called "CALL_SETUP" that will contain the time difference in seconds.
    sip_df['CALL_SETUP'] = np.nan
    sip_df['CALL_DURATION'] = np.nan
    sip_df['INVITE_TO_183_SESSION_PROGRESS'] = np.nan
    for CALL_ID in sip_df['CALL_ID'].unique():
        call_rows = sip_df[sip_df['CALL_ID'] == CALL_ID]
        if not call_rows.empty:
            # print("Processing CALL_ID:", CALL_ID)

            invite_row = call_rows[call_rows["SIP_MSG"] == "INVITE"]
            ringing_row = call_rows[call_rows["SIP_MSG"] == "180_RINGING"]
            session_progress_row = call_rows[call_rows["SIP_MSG"] == "183_SESSION_PROGRESS"]
            bye_row = call_rows[call_rows["SIP_MSG"] == "BYE"]
            if not invite_row.empty and not ringing_row.empty:
                # print("calculating the call setup time for CALL_ID:", CALL_ID)
                # print("Invite Row:", invite_row)
                # print("invite_row['Date']:", invite_row['Date'])
                # print("invite_row['Time']:", invite_row['Time'])
                invite_row['datetime'] = pd.to_datetime(invite_row['Date']+ ' ' + invite_row['Time'] , errors='coerce')
                ringing_row['datetime'] = pd.to_datetime(ringing_row['Date']  + ' ' + ringing_row['Time'] ,
                                                         errors='coerce')

                # print(invite_row['datetime'])
                # print(ringing_row['datetime'])

                invite_row = invite_row.dropna(subset=['datetime'])
                ringing_row = ringing_row.dropna(subset=['datetime'])

                if not invite_row.empty and not ringing_row.empty:
                    invite_time = invite_row['datetime'].iloc[0]
                    ringing_time = ringing_row['datetime'].iloc[0]
                    setup_duration = (ringing_time - invite_time).total_seconds()
                    sip_df.loc[call_rows.index[-1], 'CALL_SETUP'] = setup_duration
                    print("Call ID:", CALL_ID, "Setup Duration:", setup_duration, "seconds")

                # INVITE to 183 Session Progress duration
                if not invite_row.empty and not session_progress_row.empty:
                    invite_time = invite_row['datetime'].iloc[0]
                    session_progress_row['datetime'] = pd.to_datetime(session_progress_row['Date'] + ' ' + session_progress_row['Time'], errors='coerce')
                    session_progress_row = session_progress_row.dropna(subset=['datetime'])
                    if not session_progress_row.empty:
                        sp_time = session_progress_row['datetime'].iloc[0]
                        sp_duration = (sp_time - invite_time).total_seconds()
                        sip_df.loc[call_rows.index[-1], 'INVITE_TO_183_SESSION_PROGRESS'] = sp_duration
                        print("Call ID:", CALL_ID, "INVITE->183 Duration:", sp_duration, "seconds")

                if not invite_row.empty and not bye_row.empty:
                    # Calculate the call duration
                    invite_time = invite_row['datetime'].iloc[0]
                    bye_row['datetime'] = pd.to_datetime(bye_row['Date'] + ' ' + bye_row['Time'], errors='coerce')
                    bye_row = bye_row.dropna(subset=['datetime'])

                    bye_time = bye_row['datetime'].iloc[0]
                    duration = (bye_time - invite_time).total_seconds()
                    sip_df.loc[call_rows.index[-1], 'CALL_DURATION'] = duration
                    print("Call ID:", CALL_ID, "Duration:", duration, "seconds")


    # Create duplicate columns for clarity in flow
    sip_df['INVITE_TO_180_RINGING'] = sip_df['CALL_SETUP']
    sip_df['INVITE_TO_BYE'] = sip_df['CALL_DURATION']

    # Reorder columns to reflect SIP flow
    desired_flow = ['INVITE_TO_183_SESSION_PROGRESS', 'INVITE_TO_180_RINGING', 'INVITE_TO_BYE', 'CALL_SETUP', 'CALL_DURATION']
    existing_cols = list(sip_df.columns)
    # Build new order: keep all columns, but place the desired_flow block before others in that sequence
    # Start with existing, remove any of the flow columns found, then prepend them in desired order if present
    remaining = [c for c in existing_cols if c not in desired_flow]
    ordered_flow = [c for c in desired_flow if c in existing_cols]
    new_order = remaining  # default keep base order
    # Place the flow block right before exporting by inserting them after core message columns if present
    # Try to position after 'MSG_ID' if exists, else at the end prior to export
    try:
        msg_idx = remaining.index('MSG_ID') + 1
        new_order = remaining[:msg_idx] + ordered_flow + remaining[msg_idx:]
    except ValueError:
        new_order = ordered_flow + remaining

    sip_df = sip_df[new_order]

    # Save the DataFrame to a EXCEL file
    sip_df.to_excel(OUTPUT_FILE + ".xlsx", sheet_name="Data", index=False)
    # Print the DataFrame
    print(sip_df.head())

    # Print the number of unique calls
    unique_calls = sip_df['CALL_ID'].nunique()
    print(f"Number of Unique Calls: {unique_calls}")

    # Print the number of messages per call
    messages_per_call = sip_df.groupby('CALL_ID').size()
    print("Messages per Call:")
    print(messages_per_call)

    # get average call setup time by calculating the mean of the "CALL_SETUP" column but only taking into account 1 row per CALL_ID
    average_call_setup = sip_df['CALL_SETUP'].mean()
    print(f"Average Call Setup Time: {average_call_setup:.2f} seconds")

    # get average call duration by calculating the mean of the "CALL_DURATION" column but only taking into account 1 row per CALL_ID
    average_call_duration = sip_df['CALL_DURATION'].mean()
    print(f"Average Call Duration: {average_call_duration:.2f} seconds")

    # add all this information to the excel OUTPUT_FILE as a summary sheet (seperate tab)
    summary_data = {
        "Total SIP Messages": [len(sip_messages)],
        "Number of Unique Calls": [unique_calls],
        "Average Call Setup Time (seconds)": [average_call_setup],
        "Average Call Duration (seconds)": [average_call_duration],
        "Avg INVITE->183 (seconds)": [sip_df['INVITE_TO_183_SESSION_PROGRESS'].mean()]
    }
    summary_df = pd.DataFrame(summary_data)
    with pd.ExcelWriter(OUTPUT_FILE + ".xlsx", engine='openpyxl', mode='a') as writer:
        summary_df.to_excel(writer, sheet_name='Summary', index=False)

    print("Summary written to the output file.")


if __name__ == "__main__":
    main()