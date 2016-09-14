function process_drawings(subj,fn_out)
    % subj : [n x 1 cell] from javascript experiment pasted in to matlab
    % fn_out : file name for output    
    
    % Parameters
    header = 'data:image/png;base64,';

    n = length(subj);
    debug = false; % run the debugger?
    
    % Get the total number of images, since different participants
    % may have seen different images
    list_inum = [];
    for i=1:n
       strokes = subj{i}.strokes;
       input_image = subj{i}.input_image;
       nimg = length(strokes);
       for j=1:nimg
           img_name = input_image{j};
           inum = extract_num_from_string(img_name,'handwritten*.png');
           list_inum = [list_inum; inum];
       end
    end
    list_inum = unique(list_inum);
    nimg_across = max(list_inum);
    assert(isequal(vec(1:nimg_across),list_inum(:)));
    
    % initialize
    drawings = cell(nimg_across,1);
    timing = cell(nimg_across,1);
    images = cell(nimg_across,1);
    for j=1:nimg_across
        drawings{j} = cell(n,1);
        timing{j} = cell(n,1);
        images{j} = cell(n,1);
    end
    
    % make a file for each subject and each image, 
    % containing the timecourse of that image
    dir_strokes='strokes';
    dir_images='images_java';
    [~,~,~] = mkdir(dir_strokes);
    [~,~,~] = mkdir(dir_images);
   
    for i=1:n
       strokes = subj{i}.strokes;
       input_image = subj{i}.input_image;
       nimg = length(strokes);           
       
       for j=1:nimg
           img_name = input_image{j};
                      
           if isfield(subj{i},'alphabet') && ~isempty(subj{i}.alphabet) % organize by alphabaet if there are multiple alphabets
              inum = subj{i}.alphabet(j); 
           else            % organize by sequence
              inum = extract_num_from_string(img_name,'handwritten*.png');
           end
           
           % make stroke file
           fn_stroke = ['subject',num2str(i),'_image',num2str(inum),'.stroke'];
           fn_img = ['subject',num2str(i),'_image',num2str(inum)];
           fid = fopen(fullfile(dir_strokes,fn_stroke),'w');
           str_stk = subj{i}.strokes{j};
           fprintf(fid,str_stk);
           fclose(fid);
           
           % record matlab stroke data
           [mydraw,mytime,base_time] = parse_stroke(str_stk);
           drawings{inum}{i} = mydraw;
           timing{inum}{i} = mytime;
           
           % record image file
           fid = fopen(fullfile(dir_images,fn_img),'w');
           str_img = subj{i}.image{j};
           str_img = str_img(length(header)+1:end);
           fprintf(fid,str_img);
           fclose(fid);
           system(['python base64toPNG.py ',fullfile(dir_images,fn_img)]);
           I = imread(fullfile(dir_images,[fn_img,'.png']),'BackgroundColor',[1 1 1]);
           I2 = convert_to_logical(I); %% we don't want this for the
                                        % completion task, at least
           images{inum}{i} = I2;           
           viewing_images{inum}{i} = I;
           delete(fullfile(dir_images,fn_img));
           
           % %% load the image (generating ink from strokes with python)
%          I = imread(fullfile(dir_images,fn_img));
%          I = convert_to_logical(I);
%          I = image_pad(I,max_dim_size);
%          images{i}{inum} = I;

           % DEBUGGING
           if debug
               reproduce_str = write_to_string(drawing,time,base_time);
               if strcmp(str_stk,reproduce_str)
                   fprintf(1,'Test passed: raw file reproduction\n');
               else
                   error('test failed'); 
               end
           end
           
       end
    end
    
    save(fn_out,'drawings','timing','images','viewing_images');

end

% reproduce the original text
function str = write_to_string(drawing,time,base_time)
    str = '[';
    ns = length(drawing);
    for s=1:ns
        str = [str,'['];
        T = size(drawing{s},1);
        for t=1:T
            dat = drawing{s}(t,:);
            mytime = uint64(time{s}(t)) + base_time;
            str = [str,'{''x'':',num2str(dat(2)),',''y'':',num2str(dat(1)),',''t'':',num2str(mytime),'}'];
            if t < T
               str = [str,',']; 
            end
        end
        str = [str,']'];
        if s < ns
            str = [str,','];
        end
    end
    str = [str,']'];
end

%
% Takes a string representation of a drawing,
% and parses into a cell array of strokes
%
function [drawing,time,baset] = parse_stroke(str_stk)
    
    % parse into strokes
    cell_strokes = parse_into(str_stk,']');
    fclean_strokes = @(x) clean_str(x,{'[[',',['});
    cell_strokes = apply_to_nested(cell_strokes,fclean_strokes);
    cell_strokes = remove_empty_cell(cell_strokes);
    
    % parse into individual time points
    fparse_time = @(x) parse_into(x,'}');
    cell_time = apply_to_nested(cell_strokes,fparse_time);
    cell_time = remove_empty_cell(cell_time);
    fclean_time = @(x) clean_str(x,{',{','{'});
    cell_time = apply_to_nested(cell_time,fclean_time);
    cell_time = remove_empty_cell(cell_time);
    
    % clean the time points
    cell_struct = apply_to_nested(cell_time,@(x)parse_time_point(x));
    
    % process the final drawing
    ns = length(cell_struct);
    drawing = cell(ns,1);
    time = cell(ns,1);
    baset = cell_struct{1}{1}.t;
    for i=1:ns
       T = length(cell_struct{i});
       dat = zeros(T,2);
       myt = zeros(T,1);
       for t=1:T
          dat(t,:) = [cell_struct{i}{t}.y cell_struct{i}{t}.x];
          myt(t) = double(cell_struct{i}{t}.t - baset);
       end
       drawing{i} = dat;
       time{i} = myt;
    end
    
end

% removes cell of a cell array that contain empty strings
function C = remove_empty_cell(C)
    n = length(C);
    tormv = false(n,1);
    for i=1:n
        tormv(i) = isempty(C{i});
    end
    C(tormv) = [];
end


%  
% Parse a string into sub-strings,
% breaking at occurences of "delim"
% 
function C = parse_into(str,delim)
    input = str;
    remain = 'blank';
    C = [];
    while ~isempty(remain)
        [token,remain] = strtok(input,delim);
        input = remain;
        C = [C; {token}];
    end
    C = remove_empty_cell(C);
end

% For a given string, remove all 
% occurences of any of the sub-strings
% in a cell of "cell_tormv"
%
% IMPORTANT: the order matters
%
function str = clean_str(str,cell_tormv)
    n = length(cell_tormv);
    for i=1:n
       tormv = cell_tormv{i};
       str = strrep(str,tormv,'');
    end
end

function out = parse_time_point(str)
    M = textscan(str,'''x'':%d,''y'':%d,''t'':%s');
    assert(length(M)==3);
    out.x = M{1};
    out.y = M{2};
    out.t = str2num(['uint64(',M{3}{1},')']);
end